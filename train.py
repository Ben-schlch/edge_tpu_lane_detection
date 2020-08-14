
import sys
import time
import os
# import matplotlib.pyplot as plt
import tensorflow as tf
# import tensorflow_datasets.public_api as tfds
import tensorflow_model_optimization as tfmot
import numpy as np
import datetime
import cv2
import datasets
from models import AlphaLaneModel
from losses import LaneLoss

# --------------------------------------------------------------------------------------------------------------
def train(model, train_dataset, valid_batches, checkpoint_path, train_epochs=200):
    # ---------------------------
    # recover point
    checkpoint_path = os.path.join(checkpoint_path, "ccp-{epoch:04d}.ckpt")
    cp_callback = tf.keras.callbacks.ModelCheckpoint(filepath=checkpoint_path, 
                                                    verbose=1, 
                                                    save_weights_only=True,
                                                    period=2)
    log_dir = "/home/dana/tmp/logs/fit/" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    tensorboard_callback = tf.keras.callbacks.TensorBoard(log_dir=log_dir,
                                                          histogram_freq=1,
                                                        #   profile_batch = '100,110'
                                                          )
    #----------------------
    # start train
    history = model.fit(train_dataset,
                        callbacks=[cp_callback, tensorboard_callback],
                        epochs = train_epochs,
                        validation_data=valid_batches,
                        validation_freq=5)
    
    return history

# -------------------------------------------------------------------
def evaluate(model, dataset):
    model.compile(optimizer=tf.keras.optimizers.Adam(lr=0.001),
            loss=LaneLoss(),
            metrics=[tf.keras.metrics.CategoricalAccuracy()])

    print("-------------------------------------------------------------------")
    print("evaluate_model")
    test_loss, test_acc = model.evaluate(dataset, verbose=2)
    print('evaluate loss     :', test_loss)
    print('evaluate accuracy :', test_acc)

# --------------------------------------------------------------------------------------------------------------
def image_test(model, dataset, net_input_img_size, x_anchors, y_anchors, max_lane_count):
    print("-------------------------------------------------------------------")
    print("image_test")

    idx = 0
    W = 512
    H = 288
    for elem in dataset:
        # test_loss, test_acc =  model.test_on_batch (x=elem[0], y=elem[1])
        # print('test image [%d] loss: %s, accuracy %s', idx, test_loss, test_acc)
        prediction = model.predict(x=elem[0])
        main_img = np.uint8(elem[0] * 255)
        main_img = cv2.cvtColor(main_img[0], cv2.COLOR_BGR2GRAY)
        main_img = cv2.cvtColor(main_img, cv2.COLOR_GRAY2BGR)
        
        zeros = np.zeros((y_anchors,  x_anchors -1), dtype=np.uint8)
        raw_output= []
        mask = None
        for si in range(max_lane_count):
            # pred = prediction[0][si]
            pred = prediction[0,si,:, 0:127]
            output_int8 = np.uint8(pred * 255)
            if si == 0:
                img = cv2.merge([zeros, zeros, output_int8])
            elif si ==1:
                img = cv2.merge([zeros, output_int8, zeros])
            elif si ==2:
                img = cv2.merge([output_int8, zeros, zeros])
            elif si ==3:
                img = cv2.merge([zeros, output_int8, output_int8])
            else:
                img = cv2.merge([output_int8, zeros, output_int8])
            img = cv2.resize(img, (W, H))
            valu, img = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY)
            if mask is None:
                mask = img
            else:
                mask = mask + img
        # main_img = main_img + mask
        # main_img = mask
        main_img = cv2.bitwise_or (main_img, mask)

        prefix = 'build/' + str(idx)
        main_img = cv2.resize(main_img, (1280, 720))

        inv_dx = 1.0 / float(x_anchors)
        inv_dy = 1.0 / float(y_anchors)
        for dy in range(y_anchors):
            for dx in range(x_anchors):
                px = (inv_dx * dx) * 1280
                py = (inv_dy * dy) * 720
                cv2.line(main_img, (int(px), 0), (int(px), 720), (125, 125, 125))
                cv2.line(main_img, (0, int(py)), (1280, int(py)), (125, 125, 125))
        

        # cv2.imwrite(prefix + "_aaw.png", main_img)
        cv2.imshow("preview", main_img)
        key = cv2.waitKey(0)
        # cv2.destroyAllWindows()
        
        # idx += 1
        # if (idx >=100):
        #     break

# --------------------------------------------------------------------------------------------------------------
def time_test(x_in, model):
    loop_count = 200

    start = time.time()
    for i in range(loop_count):
        model.predict(x_in)
    end = time.time()
    time_predict = (end - start) / float(loop_count)
    
    start = time.time()
    for i in range(loop_count):
        model.predict_on_batch(x_in)
    end = time.time()
    time_predict_on_batch = (end - start) / float(loop_count)
    
    start = time.time()
    for i in range(loop_count):
        model(x_in, training=False)
    end = time.time()
    time_inference = (end - start) / float(loop_count)

    print("predict          avg time", time_predict, "s")
    print("predict_on_batch avg time", time_predict_on_batch, "s")
    print("inference        avg time", time_inference, "s")

# --------------------------------------------------------------------------------------------------
if __name__ == '__main__':
    # config tensorflow to prevent out of memory when training
    physical_devices = tf.config.experimental.list_physical_devices('GPU')
    assert len(physical_devices) > 0, "Not enough GPU hardware devices available"
    config = tf.config.experimental.set_memory_growth(physical_devices[0], True)


    net_input_img_size = (512, 288)
    x_anchors = 128
    y_anchors = 72
    max_lane_count = 4
    train_dataset_path = "/home/dana/Datasets/ML/TuSimple/train_set"
    train_label_set = ["label_data_0313.json",
                       "label_data_0531.json",
                       "label_data_0601.json"]

    test_dataset_path = "/home/dana/Datasets/ML/TuSimple/test_set"
    test_label_set = ["test_label.json"]

    full_dataset_path = "/home/dana/Datasets/ML/TuSimple/full_set"
    full_label_set = ["label_data_0313.json",
                      "label_data_0531.json",
                      "label_data_0601.json",
                      "test_label.json"]

    another_dataset_path = "/home/dana/Datasets/ML/TuSimple/another_test"
    another_label_set = ["test.json"]

    train_batches = datasets.TusimpleLane(full_dataset_path, full_label_set, net_input_img_size, x_anchors, y_anchors, max_lane_count, False)
    train_batches = train_batches.batch(8).shuffle(100)

    valid_batches = datasets.TusimpleLane(test_dataset_path, test_label_set, net_input_img_size, x_anchors, y_anchors, max_lane_count, False)
    # valid_batches = datasets.TusimpleLane(another_dataset_path, another_label_set, net_input_img_size, x_anchors, y_anchors, max_lane_count, False)
    valid_batches = valid_batches.batch(1)


    flag_training=False
    checkpoint_path = "tmp/non-quantized-checkpoint/"

    # model = tf.keras.models.load_model("model_result")
    model = AlphaLaneModel(net_input_img_size, x_anchors, y_anchors, max_lane_count, quantization_aware_training=False)
    model.summary()
    model.load_weights(tf.train.latest_checkpoint(checkpoint_path))
    # tf.keras.utils.plot_model(model, 'model.png')

    if flag_training:
        model.compile(optimizer=tf.keras.optimizers.Adam(lr=0.001),
                      loss=LaneLoss(),
                      metrics=[tf.keras.metrics.CategoricalAccuracy()])

        train(model, train_batches, valid_batches, checkpoint_path=checkpoint_path, train_epochs=300)
        # model.save('quantize_model_result', save_format='tf')

    print("---------------------------------------------------")
    print("mobilenetV2 time:")
    print("---------------------------------------------------")
    mobilenetV2 = tf.keras.applications.MobileNetV2()
    time_test(np.zeros((1, 224, 224, 3), dtype=np.int8), mobilenetV2)

    print("---------------------------------------------------")
    print("AlphaLaneNet time:")
    print("---------------------------------------------------")
    time_test(np.zeros((1, net_input_img_size[1], net_input_img_size[0], 3), dtype=np.int8), model)

    # image_test(model, valid_batches, net_input_img_size, x_anchors, y_anchors, max_lane_count)




    print("---------------------------------------------------")
    print("Convert model (FP16)")
    print("---------------------------------------------------")
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.target_spec.supported_types = [tf.float16]
    tflite_model = converter.convert()

    # # Save the TF Lite model.
    print("---------------------------------------------------")
    print("Save model")
    print("---------------------------------------------------")
    tflite_model_quant_file = 'model_fp16.tflite'
    with tf.io.gfile.GFile(tflite_model_quant_file, 'wb') as f:
        f.write(tflite_model)

    print("---------------------------------------------------")
    print("Load model as TF-Lite and test")
    print("---------------------------------------------------")
    interpreter = tf.lite.Interpreter(model_path=str(tflite_model_quant_file))
    interpreter.allocate_tensors()
    input_index = interpreter.get_input_details()[0]["index"]
    output_index = interpreter.get_output_details()[0]["index"]

    test_image = np.zeros((1, net_input_img_size[1], net_input_img_size[0], 3), dtype=np.float32)
    interpreter.set_tensor(input_index, test_image)
    interpreter.invoke()
    predictions = interpreter.get_tensor(output_index)

    start = time.time()
    for i in range(100):
        interpreter.set_tensor(input_index, test_image)
        interpreter.invoke()
        predictions = interpreter.get_tensor(output_index)
    end = time.time()
    time_inference = (end - start) / float(100)

    print("quantized FP16 avg time", time_inference, "s")

    sys.exit(0)