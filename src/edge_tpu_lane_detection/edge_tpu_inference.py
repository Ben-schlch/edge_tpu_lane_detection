import sys
import os
import numpy as np
import json
import cv2
import time
import json
from tflite_runtime.interpreter import Interpreter
from tflite_runtime.interpreter import load_delegate
from timer.timer import Timer
import pickle
import tensorflow as tf




# --------------------------------------------------------------------------------------------------------------

class EdgeTPUInference:
    def __init__(self, base_path: str, model_config_path: str, debug: bool = False, post_process: bool = True):
        self.config = json.load(open(model_config_path, 'r'))
        self.debug = debug
        self.post_process = post_process

        self.original_shape: list[int] | None = None

        # Load the model onto the Edge TPU
        # self.interpreter = tf.lite.Interpreter(model_path=str(tflite_model_quant_file),
        #                                   experimental_delegates=[tf.lite.experimental.load_delegate(
        #                                       "edgetpu.dll")])
        self.interpreter = Interpreter(model_path=os.path.join(base_path, "models", self.config["model_info"]["tflite_model_name"]), #),
                                       experimental_delegates=[load_delegate('libedgetpu.so.1', options={"device":":1"})])#, options={"device":":0"}
        self.interpreter.allocate_tensors()
        self.own_path = os.path.dirname(os.path.abspath(__file__))
        self.anchor_axis = pickle.load(open(f"{self.own_path}/anchor_axis.pkl", "rb"))
        # Get index of inputs and outputs, Model input information
        self.input_details = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()
        self.input_size = self.input_details[0]['shape'][1:3]
        self.roi = self.config["perspective_info"]["cutoffs"]

        _, _, _, self.max_instance_count = self.interpreter.get_output_details()[0]['shape']
        _, self.y_anchors, self.x_anchors, _ = self.interpreter.get_output_details()[0]['shape']

    def preprocess_image(self, image):
        """
            Preprocess the image (cutoff and resize)
            :param image: Image as numpy matrix to be preprocessed
        """
        # mach des hier gerne
        # cutoffs is list with 4 values: x1, y1, x2, y2
        if self.original_shape is None:
            self.original_shape = image.shape
        xl, xr, yu, yd = self.roi

        image = image[yu:yd, xl:xr]

        image = cv2.resize(image, self.input_size)
        # Normalize or other preprocessing steps if required
        return image

    def predict(self, image: np.ndarray):
        image_prep = self.preprocess_image(image)

        #if self.input_details[0]['dtype'] == np.uint8:
        #    image_prep = np.uint8(image_prep * 255)
        # else:
        #     image_prep = image_prep.astype(np.float32) / 255.0
        correctly_dimensioned_im = np.expand_dims(image_prep, axis=0)
        # print("Shape of input image: ", correctly_dimensioned_im.shape)
        self.interpreter.set_tensor(self.input_details[0]['index'], correctly_dimensioned_im)
        with Timer(name="Inference", filter_strength=40):
            self.interpreter.invoke()
        # self.interpreter.invoke()

            instance = self.interpreter.get_tensor(self.output_details[0]["index"])
            offsets = self.interpreter.get_tensor(self.output_details[1]["index"])
        #anchor_axis = self.interpreter.get_tensor(self.output_details[2]["index"])
        anchor_axis = self.anchor_axis
        with Timer(name="Postprocessing", filter_strength=40):
            lanes = self.postprocess(instance, offsets, anchor_axis)    
        #lanes = self.postprocess(instance, offsets, anchor_axis)

        # only keep the int(config["max_lane_count"]) lanes with most points
        #max_lane_count = self.config["model_info"]["max_lane_count"]
        #sorted_lanes = sorted(lanes, key=lambda x: len(x), reverse=True)
        #lanes_list = sorted_lanes[:max_lane_count]
        # check which lane is left, center or right by checking each first coordinate and sorting from low to high
        #lanes_list = sorted(lanes_list, key=lambda x: x[0][0] if len(x) > 0 else 0)
        print(f"{len(lanes[1])=} {len(lanes[5])=} {len(lanes[2])=} {len(lanes[3])=}")
        lanes_list = lanes[2], lanes[4], lanes[0]
        # print(lanes_list)
        return lanes_list

    def postprocess(self, instance, offsets, anchor_axis):
        COLORS = [(0, 0, 255), (0, 255, 0), (255, 0, 0)]
        lanes = []
        if not self.postprocess:
            
            for instanceIdx in range(self.max_instance_count):
                current_lane = []
                for dy in range(self.y_anchors):
                    for dx in range(self.x_anchors):
                        instance_prob = instance[0, dy, dx, instanceIdx]
                        offset = offsets[0, dy, dx, 0]
                        gx = anchor_axis[0, dy, dx, 0] + offset
                        gy = anchor_axis[0, dy, dx, 1]
                        current_lane.append(self.prediction_to_coordinates((gx, gy)))
                lanes.append(current_lane)

        else:
            # Check the variance of anchors by row, ideally, we want each row of instance containt only
            # zero or one valid anchor to identify instance of lane, but in some case, over one instance
            # at same row would happened. In this step, we filter anchors at each row by the x variance.
            instance = tf.convert_to_tensor(instance)
            offsets = tf.convert_to_tensor(offsets)
            anchor_axis = tf.convert_to_tensor(anchor_axis)

            anchor_x_axis = anchor_axis[:, :, :, 0]
            anchor_y_axis = anchor_axis[:, :, :, 1]
            anchor_x_axis = tf.expand_dims(anchor_x_axis, axis=-1)
            anchor_y_axis = tf.expand_dims(anchor_y_axis, axis=-1)

            instance = tf.where(instance > 0.5, 1.0, 0.0)

            anchor_x_axis = tf.add(anchor_x_axis, offsets)
            anchor_x_axis = tf.multiply(anchor_x_axis, instance)

            sum_of_instance_row = tf.reduce_sum(instance, axis=2)
            sum_of_x_axis = tf.reduce_sum(anchor_x_axis, axis=2)
            mean_of_x_axis = tf.math.divide_no_nan(sum_of_x_axis, sum_of_instance_row)
            mean_of_x_axis = tf.expand_dims(mean_of_x_axis, axis=2)
            mean_of_x_axis = tf.tile(mean_of_x_axis, [1, 1, self.x_anchors, 1])

            X_VARIANCE_THRESHOLD = 10.0
            diff_of_axis_x = tf.abs(tf.subtract(anchor_x_axis, mean_of_x_axis))
            mask_of_mean_offset = tf.where(diff_of_axis_x < X_VARIANCE_THRESHOLD, 1.0, 0.0)

            instance = tf.multiply(mask_of_mean_offset, instance)
            anchor_x_axis = tf.multiply(mask_of_mean_offset, anchor_x_axis)
            anchor_y_axis = tf.multiply(mask_of_mean_offset, anchor_y_axis)

            sum_of_instance_row = tf.reduce_sum(instance, axis=2)
            sum_of_x_axis = tf.reduce_sum(anchor_x_axis, axis=2)
            mean_of_x_axis = tf.math.divide_no_nan(sum_of_x_axis, sum_of_instance_row)

            sum_of_y_axis = tf.reduce_sum(anchor_y_axis, axis=2)
            mean_of_y_axis = tf.math.divide_no_nan(sum_of_y_axis, sum_of_instance_row)

            lanes = [[] for _ in range(self.max_instance_count)]
            for instanceIdx in range(self.max_instance_count):
                instance_mask = sum_of_instance_row[0, :, instanceIdx] > 0.5
                gx_filtered = tf.boolean_mask(mean_of_x_axis[0, :, instanceIdx], instance_mask)
                gy_filtered = tf.boolean_mask(mean_of_y_axis[0, :, instanceIdx], instance_mask)

                if len(gx_filtered) > 0:
                    gx_list = gx_filtered.numpy()
                    gy_list = gy_filtered.numpy()

                    current_lane = np.stack((gx_list, gy_list), axis=-1)
                    current_lane = [self.prediction_to_coordinates(coord) for coord in current_lane]
                    lanes[instanceIdx] = np.asarray(current_lane, dtype=np.int32)
        return lanes

    def prediction_to_coordinates(self, label):
        """
        Transform back labels and to the disired format
        """
        xl, xr, yu, yd = self.roi
        roi_width = xr - xl
        roi_height = yd - yu
        original_height, original_width, _ = self.original_shape
        # if xl < label[0] < xr and yu < label[1] < yd:
        label = (label[0] * (roi_width / 256), label[1] * (roi_height / 256))
        label = (int(label[0] + xl ), 
                     int(label[1]+ yu ))
        
        
        return label


def tflite_image_test(tflite_model_quant_file, folder_path, with_post_process=True):
    # Load the model onto the Edge TPU
    interpreter = tf.lite.Interpreter(model_path=str(tflite_model_quant_file),
                                      experimental_delegates=[tf.lite.experimental.load_delegate(
                                          "edgetpu.dll")])
    # interpreter = Interpreter(model_path=str(tflite_model_quant_file),
    #                           experimental_delegates=[load_delegate('libedgetpu.so.1')])
    interpreter.allocate_tensors()

    # Get index of inputs and outputs# Model input information
    input_details = interpreter.get_input_details()
    input_size = input_details[0]['shape'][1:3]  # Assuming input shape is in the form [1, height, width, 3]

    # Get part of data from output tensor

    COLORS = [(0, 0, 255), (0, 255, 0), (255, 0, 0),
              (0, 255, 255), (255, 0, 255), (255, 255, 0)]
    frame_count = 0
    total_inference_time = 0

    for image_name in os.listdir(folder_path):
        if image_name.lower().endswith(('.png', '.jpg', '.jpeg')):
            image_path = os.path.join(folder_path, image_name)
            image = cv2.imread(image_path)
            image = preprocess_image(image_path)  # width, height

            # Prepare input data
            if input_details[0]['dtype'] == np.uint8:
                input_data = np.uint8(image * 255)
            else:
                input_data = image.astype(np.float32) / 255.0

            start_time = time.time()

            # Inference
            start_time = time.time()
            interpreter.set_tensor(input_details[0]['index'], [input_data])
            interpreter.invoke()
            inference_time = time.time() - start_time
            print(f"Inference time: {inference_time} seconds")
            total_inference_time += inference_time
            frame_count += 1

    avg_fps = frame_count / total_inference_time
    print(f"Average FPS: {avg_fps}")
    print(f"Average inference time per frame: {total_inference_time / frame_count} seconds")


# --------------------------------------------------------------------------------------------------
if __name__ == '__main__':
    # read configs
    with open('add_ins/cvat_config2.json', 'r') as inf:
        config = json.load(inf)

    net_input_img_size = config["model_info"]["input_image_size"]
    x_anchors = config["model_info"]["x_anchors"]
    y_anchors = config["model_info"]["y_anchors"]
    max_lane_count = config["model_info"]["max_lane_count"]
    checkpoint_path = config["model_info"]["checkpoint_path"]
    tflite_model_name = config["model_info"]["tflite_model_name"]

    if not os.path.exists(tflite_model_name):
        print("tlite model doesn't exist, please run \"generate_tflite_nidel.py\" first to convert tflite model.")
        sys.exit(0)

    # set path of training data
    images = "C:/Users/inf21034/source/IMG_ROOTS/1280x960_CVATROOT/test_set/2023-10-02-12-59-12"
    # "/mnt/c/Users/inf21034/source/IMG_ROOTS/1280x960_CVATROOT/test_set"

    tflite_image_test(tflite_model_name, images)
