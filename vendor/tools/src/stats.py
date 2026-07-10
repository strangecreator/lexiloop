import numpy as np


def generate_bootstrap(
    array: np.ndarray,
    resamples_count: int,
    axis: int = 0,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    if rng is None:
        rng = np.random.default_rng()

    n = array.shape[axis]

    prefix_shape, suffix_ndim = array.shape[:axis], array.ndim - axis - 1
    indices_shape = prefix_shape + (resamples_count, n) + (1,) * suffix_ndim

    indices = rng.integers(0, n, size=indices_shape, dtype=np.intp)

    array_expanded = np.expand_dims(array, axis=axis)
    return np.take_along_axis(array_expanded, indices, axis=(axis + 1))