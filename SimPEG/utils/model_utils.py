import warnings
from typing import Literal, Optional

import discretize
import numpy as np
import scipy.sparse as sp
from discretize.utils import active_from_xyz
from scipy.interpolate import griddata
from scipy.spatial import cKDTree

from .mat_utils import mkvc

try:
    import numba
    from numba import njit, prange
except ImportError:
    numba = None

    # Define dummy njit decorator
    def njit(*args, **kwargs):
        return lambda f: f

    # Define dummy prange function
    prange = range


def surface2ind_topo(mesh, topo, gridLoc="CC", method="nearest", fill_value=np.nan):
    """Get indices of active cells from topography.

    For a mesh and surface topography, this function returns the indices of cells
    lying below the discretized surface topography.

    Parameters
    ----------
    mesh : discretize.TensorMesh or discretize.TreeMesh
        Mesh on which you want to identify active cells
    topo : (n, 3) numpy.ndarray
        Topography data as a ``numpyndarray`` with columns [x,y,z]; can use [x,z] for 2D meshes.
        Topography data can be unstructured.
    gridLoc : str {'CC', 'N'}
        If 'CC', all cells whose centers are below the topography are active cells.
        If 'N', then cells must lie entirely below the topography in order to be active cells.
    method : str {'nearest','linear'}
        Interpolation method for approximating topography at cell's horizontal position.
        Default is 'nearest'.
    fill_value : float
        Defines the elevation for cells outside the horizontal extent of the topography data.
        Default is :py:class:`numpy.nan`.

    Returns
    -------
    (n_active) numpy.ndarray of int
        Indices of active cells below xyz.
    """
    warnings.warn(
        "The surface2ind_topo function has been deprecated, please import "
        "discretize.utils.active_from_xyz. This will be removed in SimPEG 0.20.0",
        FutureWarning,
        stacklevel=2,
    )

    active_cells = active_from_xyz(mesh, topo, gridLoc, method)
    return np.arange(mesh.n_cells)[active_cells]


def surface_layer_index(mesh, topo, index=0):
    """Find ith layer of cells below topo for a tensor mesh.

    Parameters
    ----------
    mesh : discretize.TensorMesh
        Input mesh
    topo : (n, 3) numpy.ndarray
        Topography data as a numpy array with columns [x,y,z]; can use [x,z] for 2D meshes.
        Topography data can be unstructured.
    index : int
        How many layers below the surface you want to find

    Returns
    -------
    numpy.ndarray of int
        Index vector for layer of cells
    """

    actv = np.zeros(mesh.nC, dtype="bool")
    # Get cdkTree to find top layer
    tree = cKDTree(mesh.gridCC)

    def ismember(a, b):
        bind = {}
        for i, elt in enumerate(b):
            if elt not in bind:
                bind[elt] = i
        return np.vstack([bind.get(itm, None) for itm in a])

    grid_x, grid_y = np.meshgrid(mesh.cell_centers_x, mesh.cell_centers_y)
    zInterp = mkvc(
        griddata(topo[:, :2], topo[:, 2], (grid_x, grid_y), method="nearest")
    )

    # Get nearest cells
    r, inds = tree.query(np.c_[mkvc(grid_x), mkvc(grid_y), zInterp])
    inds = np.unique(inds)

    # Extract vertical neighbors from Gradz operator
    Dz = mesh.stencil_cell_gradient_z
    Iz, Jz, _ = sp.find(Dz)
    jz = np.sort(Jz[np.argsort(Iz)].reshape((int(Iz.shape[0] / 2), 2)), axis=1)
    for _ in range(index):
        members = ismember(inds, jz[:, 1])
        inds = np.squeeze(jz[members, 0])

    actv[inds] = True

    return actv


def depth_weighting(
    mesh, reference_locs, active_cells=None, exponent=2.0, threshold=None, **kwargs
):
    r"""
    Construct diagonal elements of a depth weighting matrix

    Builds the model weights following the depth weighting strategy, a method
    to generate weights based on the vertical distance between mesh cell
    centers and some reference location(s).
    Use these weights in regularizations to counteract the natural decay of
    potential field data with depth.

    Parameters
    ----------
    mesh : discretize.base.BaseMesh
        Discretized model space.
    reference_locs : float or (n, ndim) numpy.ndarray
        Reference location for the depth weighting.
        It can be a ``float``, which value is the vertical component for
        the reference location.
        Or it can be a 2d array, with multiple reference locations, where each
        row should contain the coordinates of a single location point in the
        following order: _x_, _y_, _z_ (for 3D meshes) or _x_, _z_ (for 2D
        meshes).
        The vertical coordinate of the reference location for each cell in the
        mesh will be obtained by the closest point in ``reference_locs`` using
        only their horizontal coordinates.
    active_cells : (mesh.n_cells) numpy.ndarray of bool, optional
        Index vector for the active cells on the mesh.
        If ``None``, every cell will be assumed to be active.
    exponent : float, optional
        Exponent parameter for depth weighting.
        The exponent should match the natural decay power of the potential
        field. For example, for gravity acceleration, set it to 2; for magnetic
        fields, to 3.
    threshold : float or None, optional
        Threshold parameters used in the depth weighting.
        If ``None``, it will be set to half of the smallest cell width.

    Returns
    -------
    (n_active) numpy.ndarray
        Normalized depth weights for the mesh at every active cell as
        a 1d-array.

    Notes
    -----
    Each diagonal term of the matrix is defined as:

    .. math::

        w(z) = \frac{1}{(|z - z_0| + \epsilon) ^ {\nu / 2}}

    where :math:`z` is the vertical coordinate of the mesh cell centers,
    :math:`z_0` is the vertical coordinate of the reference location,
    :math:`\nu` is the _exponent_,
    and :math:`\epsilon` is a given _threshold_.

    The depth weights array is finally normalized by dividing for its maximum
    value.
    """

    if "indActive" in kwargs:
        warnings.warn(
            "The indActive keyword argument has been deprecated, please use active_cells. "
            "This will be removed in SimPEG 0.19.0",
            FutureWarning,
            stacklevel=2,
        )
        active_cells = kwargs["indActive"]

    # Default threshold value
    if threshold is None:
        threshold = 0.5 * mesh.h_gridded.min()

    reference_locs = np.asarray(reference_locs)

    # Calculate depth from receiver locations, delta_z
    # reference_locs is a scalar
    if reference_locs.ndim < 2:
        delta_z = np.abs(mesh.cell_centers[:, -1] - reference_locs)

    # reference_locs is a 2d array
    elif reference_locs.ndim == 2:
        tree = cKDTree(reference_locs[:, :-1])
        _, ind = tree.query(mesh.cell_centers[:, :-1])
        delta_z = np.abs(mesh.cell_centers[:, -1] - reference_locs[ind, -1])

    else:
        raise ValueError("reference_locs must be either a scalar or 2d array!")

    wz = (delta_z + threshold) ** (-0.5 * exponent)

    if active_cells is not None:
        wz = wz[active_cells]

    return wz / np.nanmax(wz)


@njit(parallel=True)
def _distance_weighting_numba(
    cell_centers: np.ndarray,
    cell_volumes: np.ndarray,
    reference_locs: np.ndarray,
    threshold: float,
    exponent: float = 2.0,
) -> np.ndarray:
    r"""
    distance weighting kernel in numba.

    If numba is not installed, this will work as a regular for loop.

    Parameters
    ----------
    cell_centers : np.ndarray
        cell centers of the mesh.
    cell_volumes : np.ndarray
        cell volumes of the mesh.
    reference_locs : float or (n, ndim) numpy.ndarray
        Reference location for the distance weighting.
        It can be a ``float``, which value is the component for
        the reference location.
        Or it can be a 2d array, with multiple reference locations, where each
        row should contain the coordinates of a single location point in the
        following order: _x_, _y_, _z_ (for 3D meshes) or _x_, _z_ (for 2D
        meshes).
        The coordinate of the reference location, usually the receiver locations
    exponent : float, optional
        Exponent parameter for distance weighting.
        The exponent should match the natural decay power of the potential
        field. For example, for gravity acceleration, set it to 2; for magnetic
        fields, to 3.
    threshold : float or None, optional
        Threshold parameters used in the distance weighting.
        If ``None``, it will be set to half of the smallest cell width.

    Returns
    -------
    (n_active) numpy.ndarray
        Normalized distance weights for the mesh at every active cell as
        a 1d-array.
    """

    distance_weights = np.zeros(len(cell_centers))
    n_reference_locs = len(reference_locs)
    for i in prange(n_reference_locs):
        rl = reference_locs[i]
        dst_wgt = (
            np.sqrt(((cell_centers - rl) ** 2).sum(axis=1)) + threshold
        ) ** exponent
        dst_wgt = (cell_volumes / dst_wgt) ** 2
        distance_weights += dst_wgt

    distance_weights = distance_weights**0.5
    distance_weights /= cell_volumes
    distance_weights /= np.nanmax(distance_weights)

    return distance_weights


def distance_weighting(
    mesh: discretize.base.BaseMesh,
    reference_locs: np.ndarray,
    active_cells: Optional[np.ndarray] = None,
    exponent: float = 2.0,
    threshold: Optional[float] = None,
    engine: Literal["loop", "vector"] = "loop",
):
    r"""
    Construct diagonal elements of a distance weighting matrix

    Builds the model weights following the distance weighting strategy, a method
    to generate weights based on the distance between mesh cell centers and some
    reference location(s).
    Use these weights in regularizations to counteract the natural decay of
    potential field data with distance.

    Parameters
    ----------
    mesh : discretize.base.BaseMesh
        Discretized model space.
    reference_locs : float or (n, ndim) numpy.ndarray
        Reference location for the distance weighting.
        It can be a ``float``, which value is the component for
        the reference location.
        Or it can be a 2d array, with multiple reference locations, where each
        row should contain the coordinates of a single location point in the
        following order: _x_, _y_, _z_ (for 3D meshes) or _x_, _z_ (for 2D
        meshes).
        The coordinate of the reference location, usually the receiver locations
    active_cells : (mesh.n_cells) numpy.ndarray of bool, optional
        Index vector for the active cells on the mesh.
        If ``None``, every cell will be assumed to be active.
    exponent : float, optional
        Exponent parameter for distance weighting.
        The exponent should match the natural decay power of the potential
        field. For example, for gravity acceleration, set it to 2; for magnetic
        fields, to 3.
    threshold : float or None, optional
        Threshold parameters used in the distance weighting.
        If ``None``, it will be set to half of the smallest cell width.
    engine: str, 'loops' or 'vector': pick between a `vector` vectorized computation (memory intensive) or `for` loop
        implementation, parallelized with numba if available. Default to 'loop'.

    Returns
    -------
    (n_active) numpy.ndarray
        Normalized distance weights for the mesh at every active cell as
        a 1d-array.
    """
    if (numba is None) and (engine == "loop"):
        warnings.warn(
            "numba is not installed. 'For loops' computations might be slower.",
            stacklevel=2,
        )

    active_cells = (
        np.ones(mesh.n_cells, dtype=bool) if active_cells is None else active_cells
    )

    # Default threshold value
    if threshold is None:
        threshold = 0.5 * mesh.h_gridded.min()

    reference_locs = np.asarray(reference_locs)

    cell_centers = mesh.cell_centers[active_cells]
    cell_volumes = mesh.cell_volumes[active_cells]

    # address 1D case
    if mesh.dim == 1:
        cell_centers = cell_centers.reshape(-1, 1)
        reference_locs = reference_locs.reshape(-1, 1)

    if engine == "loop":
        distance_weights = _distance_weighting_numba(
            cell_centers,
            cell_volumes,
            reference_locs,
            exponent=exponent,
            threshold=threshold,
        )

    elif engine == "vector":
        n, d = cell_centers.shape
        t, d1 = reference_locs.shape
        if not d == d1:
            raise Exception("vectors must have same number of columns")

        # vectorized distance calculations
        distance = (
            np.dot((cell_centers**2.0), np.ones([d, t]))
            + np.dot(np.ones([n, d]), (reference_locs**2.0).T)
            - 2.0 * np.dot(cell_centers, reference_locs.T)
        ) ** 0.5

        distance_weights = (
            (cell_volumes.reshape(-1, 1) / ((distance + threshold) ** exponent)) ** 2
        ).sum(axis=1)

        distance_weights = distance_weights**0.5
        distance_weights /= cell_volumes
        distance_weights /= np.nanmax(distance_weights)

    else:
        raise ValueError(
            f"engine should be either 'vector' or 'loop', instead {engine=}"
        )

    return distance_weights
