import sys
import os
import matplotlib.pyplot as plt
import tensorflow as tf
import datetime
import json
import cv2
import datasets
import datasets.cvat_dataset
from datasets.cvat_dataset.cvat_dataset_dataset_builder import Builder
import tensorflow_datasets as tfds
from models import AlphaLaneModel
from losses import LaneLoss
import time
import keras
from eval import LaneDetectionEval


def augment_image(image_label, seed):
    image, label = image_label
    image = tf.image.stateless_random_brightness(image, 0.1, seed=seed)
    image = tf.image.stateless_random_contrast(image, 0.2, 0.85, seed=seed)
    # image = tf.image.random_flip_left_right(image)
    return image, label


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

    # enable memory growth to prevent out of memory when training
    physical_devices = tf.config.list_physical_devices('GPU')
    assert len(physical_devices) > 0, "Not enough GPU hardware devices available"
    for device in physical_devices:
        tf.config.experimental.set_memory_growth(device, True)
    # tf.config.experimental.set_memory_growth(physical_devices[0], True)

    # set path of training data
    train_dataset_path = "/mnt/c/Users/inf21034/source/IMG_ROOTS/1280x960_CVATROOT/train_set"
    # "/mnt/c/Users/inf21034/source/IMG_ROOTS/TUSIMPLEROOT/TUSimple"
    #
    train_label_set = ["train_set.json"]
    """["label_data_0313.json",
                       "label_data_0531.json",
                       "label_data_0601.json"]"""
    test_dataset_path = "/mnt/c/Users/inf21034/source/IMG_ROOTS/1280x960_CVATROOT/test_set"
    # "/mnt/c/Users/inf21034/source/IMG_ROOTS/TUSIMPLEROOT/TUSimple"
    #
    test_label_set = ["test_set.json"]

    rng = tf.random.Generator.from_seed(int(time.time()), alg='philox')


    def f(image, label):
        seed = rng.make_seeds(1)[:, 0]
        image, label = augment_image((image, label), seed)
        return image, label


    # create dataset
    augmentation = True
    batch_size = 32
    train_batches = tfds.load('cvat_dataset',
                              split='train',
                              shuffle_files=True,
                              as_supervised=True,
                              batch_size=batch_size)
    train_batches = train_batches.prefetch(tf.data.experimental.AUTOTUNE)
    train_batches = train_batches.map(f, num_parallel_calls=tf.data.experimental.AUTOTUNE)
    # datasets.TusimpleLane(train_dataset_path, train_label_set, config, augmentation=augmentation).get_pipe()
    # train_batches = train_batches.shuffle(1000).batch(batch_size)
    # print("Training batches: ", list(train_batches.as_numpy_iterator()))

    valid_batches: tf.data.Dataset = tfds.load('cvat_dataset', split='test', shuffle_files=True, as_supervised=True)
    # valid_batches = valid_batches.prefetch(tf.data.experimental.AUTOTUNE)
    # datasets.TusimpleLane(test_dataset_path, test_label_set, config, augmentation=False).get_pipe()
    valid_batches = valid_batches.batch(1)

    # tf.debugging.disable_traceback_filtering()
    # create model
    model: keras.Model = AlphaLaneModel(net_input_img_size, x_anchors, y_anchors,
                                        training=True,
                                        name='AlphaLaneNet',
                                        input_batch_size=batch_size)
    model.summary()

    # Enable to load weights from previous training.
    # model.load_weights(tf.train.latest_checkpoint(checkpoint_path))     # load p/retrained

    # set path of checkpoint
    ln_scheduler = keras.optimizers.schedules.ExponentialDecay(0.001, 1000, 0.9)
    early_stopping = keras.callbacks.EarlyStopping(monitor='val_loss', patience=10, verbose=1)
    model.compile(optimizer=keras.optimizers.Nadam(learning_rate=ln_scheduler),
                  loss=[LaneLoss()],
                  run_eagerly=False)
    # metrics=[LaneDetectionEval.local_f1])

    checkpoint_path = os.path.join(checkpoint_path, "ccp-{epoch:04d}.ckpt")
    cp_callback = keras.callbacks.ModelCheckpoint(filepath=checkpoint_path,
                                                  verbose=1,
                                                  save_weights_only=True,
                                                  save_freq='epoch')
    # start train
    history = model.fit(train_batches,
                        validation_data=valid_batches,
                        callbacks=[cp_callback, early_stopping],
                        epochs=200)

    print("Training finish ...")
