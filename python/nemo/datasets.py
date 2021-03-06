from collections import namedtuple

import tensorflow as tf
from tensorflow import keras

import yaml

from nemo.images import augment_image, load_and_preprocess_image


# Used for auto-tuning dataset prefetch size, etc.
AUTOTUNE = tf.data.experimental.AUTOTUNE
BATCH_SIZE = 32


def labels_for_dir(path):
    labels = sorted(child.name for child in path.glob("*/") if child.is_dir())
    labels = dict((name, index) for index, name in enumerate(labels))
    return labels


def save_labels(path, labels):
    with path.open("w") as f:
        yaml.safe_dump(labels, f)


def read_labels(path):
    with path.open("r") as f:
        return yaml.safe_load(f)


def dataset_from_dir(source_dir, label_lookup, return_files=False):
    files = sorted([file for file in source_dir.rglob("*.png")])

    # Extract labels based on directory structure convention.
    labels = [label_lookup[file.parent.name] for file in files]
    labels = keras.utils.to_categorical(labels, len(label_lookup))

    # Tensors can't represent Path objects; use strings instead.
    files = [str(file) for file in files]
    dataset = tf.data.Dataset.from_tensor_slices((files, labels))

    if return_files:
        return dataset, len(files), files

    return dataset, len(files)


def load_datasets(data_dir):
    # TODO: Make these configurable?
    train_dir = data_dir / "train"
    valid_dir = data_dir / "valid"
    test_dir = data_dir / "test"

    # Fetch labels as a map from names to indices.
    labels = labels_for_dir(train_dir)

    # Prepare training dataset.
    train_dataset, train_count = dataset_from_dir(train_dir, labels)
    train_dataset = train_dataset.shuffle(train_count)
    train_dataset = train_dataset.map(load_and_preprocess_image, num_parallel_calls=AUTOTUNE)

    # TODO: Consider moving this block to call site.
    train_dataset = train_dataset.map(augment_image, num_parallel_calls=AUTOTUNE)
    train_dataset = train_dataset.batch(BATCH_SIZE)
    train_dataset = train_dataset.prefetch(AUTOTUNE)

    # Prepare validation dataset.
    valid_dataset, valid_count = dataset_from_dir(valid_dir, labels)
    valid_dataset = valid_dataset.shuffle(valid_count)
    valid_dataset = valid_dataset.map(load_and_preprocess_image, num_parallel_calls=AUTOTUNE)

    # TODO: Consider moving this block to call site.
    valid_dataset = valid_dataset.batch(BATCH_SIZE)
    valid_dataset = valid_dataset.prefetch(AUTOTUNE)

    # Prepare test dataset.
    test_dataset, test_count = dataset_from_dir(test_dir, labels)
    test_dataset = test_dataset.shuffle(test_count)
    test_dataset = test_dataset.map(load_and_preprocess_image, num_parallel_calls=AUTOTUNE)

    # TODO: Consider moving this block to call site.
    test_dataset = test_dataset.batch(BATCH_SIZE)
    test_dataset = test_dataset.prefetch(AUTOTUNE)

    Metadata = namedtuple("Metadata", ["labels", "train_count", "valid_count", "test_count"])
    metadata = Metadata(labels, train_count, valid_count, test_count)

    return train_dataset, valid_dataset, test_dataset, metadata
