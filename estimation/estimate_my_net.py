import tensorflow as tf
import numpy as np
slim = tf.contrib.slim
tfrecords_filename = '../data_preprocessing/chamo.tfrecord'
import matplotlib.pyplot as plt
_RESIZE_SIDE_MIN = 256
_RESIZE_SIDE_MAX = 256
_R_MEAN = 123.68
_G_MEAN = 116.78
_B_MEAN = 103.94
def _crop(image, offset_height, offset_width, crop_height, crop_width):
    original_shape = tf.shape(image)
    rank_assertion = tf.Assert(tf.equal(tf.rank(image), 3),['Rank of image must be equal to 3.'])
    with tf.control_dependencies([rank_assertion]):
        cropped_shape = tf.stack([crop_height, crop_width, original_shape[2]])
    size_assertion = tf.Assert(
        tf.logical_and(
            tf.greater_equal(original_shape[0], crop_height),
            tf.greater_equal(original_shape[1], crop_width)),
        ['Crop size greater than the image size.'])
    offsets = tf.to_int32(tf.stack([offset_height, offset_width, 0]))
    with tf.control_dependencies([size_assertion]):
        image = tf.slice(image, offsets, cropped_shape)
    return tf.reshape(image, cropped_shape)

def _random_crop(image_list, crop_height, crop_width):
    if not image_list:
        raise ValueError('Empty image_list.')
    rank_assertions = []
    for i in range(len(image_list)):
        image_rank = tf.rank(image_list[i])
        rank_assert = tf.Assert(
            tf.equal(image_rank, 3),
            ['Wrong rank for tensor  %s [expected] [actual]',
             image_list[i].name, 3, image_rank])
        rank_assertions.append(rank_assert)

    with tf.control_dependencies([rank_assertions[0]]):
        image_shape = tf.shape(image_list[0])
    image_height = image_shape[0]
    image_width = image_shape[1]
    crop_size_assert = tf.Assert(
        tf.logical_and(
            tf.greater_equal(image_height, crop_height),
            tf.greater_equal(image_width, crop_width)),
        ['Crop size greater than the image size.'])

    asserts = [rank_assertions[0], crop_size_assert]

    for i in range(1, len(image_list)):
        image = image_list[i]
        asserts.append(rank_assertions[i])
        with tf.control_dependencies([rank_assertions[i]]):
            shape = tf.shape(image)
        height = shape[0]
        width = shape[1]

        height_assert = tf.Assert(
            tf.equal(height, image_height),
            ['Wrong height for tensor %s [expected][actual]',
             image.name, height, image_height])
        width_assert = tf.Assert(
            tf.equal(width, image_width),
            ['Wrong width for tensor %s [expected][actual]',
             image.name, width, image_width])
        asserts.extend([height_assert, width_assert])

    with tf.control_dependencies(asserts):
        max_offset_height = tf.reshape(image_height - crop_height + 1, [])
    with tf.control_dependencies(asserts):
        max_offset_width = tf.reshape(image_width - crop_width + 1, [])
    offset_height = tf.random_uniform([], maxval=max_offset_height, dtype=tf.int32)
    offset_width = tf.random_uniform([], maxval=max_offset_width, dtype=tf.int32)

    return [_crop(image, offset_height, offset_width, crop_height, crop_width) for image in image_list]

def _smallest_size_at_least(height, width, smallest_side):
    smallest_side = tf.convert_to_tensor(smallest_side, dtype=tf.int32)
    height = tf.to_float(height)
    width = tf.to_float(width)
    smallest_side = tf.to_float(smallest_side)
    scale = tf.cond(tf.greater(height, width),lambda: smallest_side / width,lambda: smallest_side / height)
    new_height = tf.to_int32(tf.rint(height * scale))
    new_width = tf.to_int32(tf.rint(width * scale))
    return new_height, new_width

def _aspect_preserving_resize(image, smallest_side):
    smallest_side = tf.convert_to_tensor(smallest_side, dtype=tf.int32)
    shape = tf.shape(image)
    height = shape[0]
    width = shape[1]
    new_height, new_width = _smallest_size_at_least(height, width, smallest_side)
    image = tf.expand_dims(image, 0)
    resized_image = tf.image.resize_bilinear(image, [new_height, new_width],align_corners=False)
    resized_image = tf.squeeze(resized_image)
    resized_image.set_shape([None, None, 3])
    return resized_image

def _mean_image_subtraction(image, means):
    if image.get_shape().ndims != 3:
        raise ValueError('Input must be of size [height, width, C>0]')
    num_channels = image.get_shape().as_list()[-1]
    if len(means) != num_channels:
        raise ValueError('len(means) must match the number of channels')
    channels = tf.split(axis=2, num_or_size_splits=num_channels, value=image)
    for i in range(num_channels):
        channels[i] -= means[i]
    return tf.concat(axis=2, values=channels)

def preprocess_for_train(image,
                         output_height,
                         output_width,
                         resize_side_min=_RESIZE_SIDE_MIN,
                         resize_side_max=_RESIZE_SIDE_MAX):
    resize_side = tf.random_uniform([], minval=resize_side_min, maxval=resize_side_max+1, dtype=tf.int32)
    #tf.summary.scalar('loss', resize_side)
    image = _aspect_preserving_resize(image, resize_side)
    image = _random_crop([image], output_height, output_width)[0]
    image.set_shape([output_height, output_width, 3])
    image = tf.to_float(image)
    image = tf.image.random_flip_left_right(image)
    #return _mean_image_subtraction(image, [_R_MEAN, _G_MEAN, _B_MEAN])
    return image

def vgg_16(inputs,
           num_classes=1,
           is_training=True,
           dropout_keep_prob=0.5,
           spatial_squeeze=True,
           scope='vgg_16',
           fc_conv_padding='VALID',
           global_pool=False):
    with tf.variable_scope(scope, 'vgg_16', [inputs]) as sc:
        end_points_collection = sc.original_name_scope + '_end_points'
        # Collect outputs for conv2d, fully_connected and max_pool2d.
        with slim.arg_scope([slim.conv2d, slim.fully_connected, slim.max_pool2d],
                            outputs_collections=end_points_collection):
            net = slim.repeat(inputs, 2, slim.conv2d, 64, [3, 3], scope='conv1')
            net = slim.max_pool2d(net, [2, 2], scope='pool1')
            net = slim.repeat(net, 2, slim.conv2d, 128, [3, 3], scope='conv2')
            net = slim.max_pool2d(net, [2, 2], scope='pool2')
            net = slim.repeat(net, 3, slim.conv2d, 256, [3, 3], scope='conv3')
            net = slim.max_pool2d(net, [2, 2], scope='pool3')
            net = slim.repeat(net, 3, slim.conv2d, 512, [3, 3], scope='conv4')
            net = slim.max_pool2d(net, [2, 2], scope='pool4')
            net = slim.repeat(net, 3, slim.conv2d, 512, [3, 3], scope='conv5')
            net = slim.max_pool2d(net, [2, 2], scope='pool5')

            # Use conv2d instead of fully_connected layers.
            net = slim.conv2d(net, 4096, [7, 7], padding=fc_conv_padding, scope='fc6')
            net = slim.dropout(net, dropout_keep_prob, is_training=is_training,
                               scope='dropout6')
            net = slim.conv2d(net, 4096, [1, 1], scope='fc7')
            # Convert end_points_collection into a end_point dict.
            end_points = slim.utils.convert_collection_to_dict(end_points_collection)
            if num_classes:
                net = slim.dropout(net, dropout_keep_prob, is_training=is_training,scope='dropout7')
                net = slim.conv2d(net, num_classes, [1, 1],activation_fn=None,normalizer_fn=None,scope='fc8')
                end_points[sc.name + '/fc8'] = net
            return net, end_points

filename_queue = tf.train.string_input_producer([tfrecords_filename])
reader = tf.TFRecordReader()
_, serialized_example = reader.read(filename_queue)
features = tf.parse_single_example(serialized_example,
                                   features={
                                       'label': tf.FixedLenFeature([], tf.int64),
                                       'img_raw': tf.FixedLenFeature([], tf.string),
                                       'img_width': tf.FixedLenFeature([], tf.int64),
                                       'img_height': tf.FixedLenFeature([], tf.int64),
                                   })
height = tf.cast(features['img_height'], tf.int32)
width = tf.cast(features['img_width'], tf.int32)
image = tf.decode_raw(features['img_raw'], tf.uint8)
channel = 3
image = tf.reshape(image, [height, width, channel])
label = tf.cast(features['label'], tf.float32)
train_image_size = 224
image = preprocess_for_train(image,train_image_size, train_image_size)
#merged = tf.summary.merge_all()
batch_size=10
images, labels = tf.train.batch([image, label] ,batch_size=batch_size, num_threads=1, capacity=5 * batch_size)
net, end_points = vgg_16(images)
net=tf.tanh(net)
net=tf.squeeze(net)
mse = tf.reduce_sum(tf.square(labels -  net))
train_step = tf.train.AdamOptimizer(1e-4).minimize(mse)
init_op = tf.global_variables_initializer()
with tf.Session() as sess:
    sess.run(init_op)
    coord = tf.train.Coordinator()
    threads = tf.train.start_queue_runners(coord=coord)

    writer = tf.summary.FileWriter("logs/", sess.graph)

    for i in range(1000):
        sess.run(train_step)
        if i % 1 == 0:
            re=sess.run(net)
            for k in range(len(re)):
                print('%f ' % re[k], end='')
            print('')
            label_python=sess.run(labels)
            for k in range(len(label_python)):
                print('%f ' % label_python[k], end='')
            print('')
            print(sess.run(mse))
            re=np.squeeze(re)
            print(np.sum((re-label_python)*(re-label_python)))
        # image_batch_v, label_batch_v = sess.run([images, labels])
        # for k in range(len(image_batch_v)):
        #     processed_img = image_batch_v[k]
        #     processed_img = processed_img / 255
        #     plt.imshow(processed_img)
        #     plt.show()
    coord.request_stop()
    coord.join(threads)