import numpy as np
import properties

from .... import survey
from ....utils import Zero, closest_points_index
from .receivers import BaseRx


class BaseSrc(survey.BaseSrc):
    """Base DC/IP source

    Parameters
    ----------
    receiver_list : list of SimPEG.electromagnetics.static.resistivity.receivers.BaseRx
        A list of DC/IP receivers
    location : (dim) np.ndarray
        Source location
    current : float, default=1.0
        Current amplitude [A]
    """

    # current = properties.Float("amplitude of the source current", default=1.0)

    _q = None

    def __init__(self, receiver_list, location, current=1.0, **kwargs):
        super(BaseSrc, self).__init__(receiver_list=receiver_list, location=location, **kwargs)
        self.current = current

    @property
    def receiver_list(self):
        """List of receivers associated with the source

        Returns
        -------
        list of SimPEG.electromagnetics.static.resistivity.receivers.BaseRx
            List of receivers associated with the source
        """
        return self._receiver_list

    @receiver_list.setter
    def receiver_list(self, new_list):

        if isinstance(new_list, BaseRx):
            new_list = [new_list]
        elif isinstance(new_list, list):
            pass
        else:
            raise TypeError("Receiver list must be a list of SimPEG.electromagnetics.static.resistivity.receivers.BaseRx")

        assert len(set(new_list)) == len(new_list), "The receiver_list must be unique. Cannot re-use receivers"

        self._rxOrder = dict()
        [self._rxOrder.setdefault(rx._uid, ii) for ii, rx in enumerate(new_list)]
        self._receiver_list = new_list


    @property
    def current(self):
        """Source current

        Returns
        -------
        float
            Source current
        """
        return self._current

    @current.setter
    def current(self, I):
        try:
            I = float(I)
        except:
            raise TypeError(f"current must be int or float, got {type(I)}")

        if np.abs(I) == 0.:
            raise TypeError("current must be non-zero.")

        self._current = I

    def eval(self, sim):
        """Not implemented for BaseSrc"""
        raise NotImplementedError(
            "the eval method for {} has not been implemented".format(self)
        )

    def evalDeriv(self, sim):
        """Returns zero"""
        return Zero()


class Dipole(BaseSrc):
    """Dipole source

    Parameters
    ----------
    receiver_list : list of SimPEG.electromagnetics.static.resistivity.receivers.BaseRx
        A list of DC/IP receivers
    location_a : (dim) numpy.array_like
        A electrode location; remember to set 'location_b' keyword argument to define N electrode locations.
    location_b : (dim) numpy.array_like
        B electrode location; remember to set 'location_a' keyword argument to define M electrode locations.
    location : list or tuple of length 2 of numpy.array_like
        A and B electrode locations. In this case, do not set the 'location_a' and 'location_b'
        keyword arguments. And we supply a list or tuple of the form [location_a, location_b].
    current : float, default=1.0
        Current amplitude [A]
    """

    # location = properties.List(
    #     "location of the source electrodes",
    #     survey.SourceLocationArray("location of electrode"),
    # )

    def __init__(
        self,
        receiver_list=None,
        location_a=None,
        location_b=None,
        location=None,
        **kwargs,
    ):
        # Check for old keywords
        if "locationA" in kwargs.keys():
            location_a = kwargs.pop("locationA")
            raise TypeError(
                "The locationA property has been removed. Please set the "
                "location_a property instead.",
            )

        if "locationB" in kwargs.keys():
            location_b = kwargs.pop("locationB")
            raise TypeError(
                "The locationB property has been removed. Please set the "
                "location_b property instead.",
            )

        # if location_a set, then use location_a, location_b
        if location_a is not None:
            if location_b is None:
                raise ValueError(
                    "For a dipole source both location_a and location_b " "must be set"
                )

            if location is not None:
                raise ValueError(
                    "Cannot set both location and location_a, location_b. "
                    "Please provide either location=(location_a, location_b) "
                    "or both location_a=location_a, location_b=location_b"
                )

            location = [location_a, location_b]

        if location is None:
            raise AttributeError(
                "Source cannot be instantiated without assigning 'location'."
                "Please provide either location=(location_a, location_b) "
                "or both location_a=location_a, location_b=location_b"
            )

        # instantiate
        super(Dipole, self).__init__(receiver_list, location=location, **kwargs)
        # self.location = location

    def __repr__(self):
        return (
            f"{self.__class__.__name__}(" f"a: {self.location_a}; b: {self.location_b})"
        )

    @property
    def location(self):
        """A and N electrode locations

        Returns
        -------
        list of np.ndarray of the form [dim, dim]
            A and B electrode locations.
        """
        return self._locations

    @location.setter
    def location(self, locs):
        if len(locs) != 2:
            raise ValueError(
                    "locations must be a list or tuple of length 2: "
                    "[location_a, location_b. The input locations has "
                    f"length {len(locs)}"
                )
        
        locs = [np.atleast_1d(locs[0]), np.atleast_1d(locs[1])]

        # check the size of locations_m, locations_n
        if locs[0].shape != locs[1].shape:
            raise ValueError(
                f"location_a (shape: {locs[0].shape}) and "
                f"location_b (shape: {locs[1].shape}) need to be "
                f"the same size"
            )
            
        self._locations = locs

    @property
    def location_a(self):
        """Location of the A-electrode

        Returns
        -------
        (dim) numpy.ndarray
            Location of the A-electrode
        """
        return self.location[0]

    @property
    def location_b(self):
        """Location of the B-electrode

        Returns
        -------
        (dim) numpy.ndarray
            Location of the B-electrode
        """
        return self.location[1]

    def eval(self, sim):
        """Project source to mesh.

        Parameters
        ----------
        sim : SimPEG.electromagnetics.static.resistivity.simulation.BaseDCSimulation
            A DC/IP simulation
        
        Returns
        -------
        np.ndarray
            Discretize source term on the mesh
        """
        if self._q is not None:
            return self._q
        else:
            if sim._formulation == "HJ":
                inds = closest_points_index(sim.mesh, self.location, gridLoc="CC")
                self._q = np.zeros(sim.mesh.nC)
                self._q[inds] = self.current * np.r_[1.0, -1.0]
            elif sim._formulation == "EB":
                qa = sim.mesh.get_interpolation_matrix(
                    self.location[0], location_type="N"
                ).toarray()
                qb = -sim.mesh.get_interpolation_matrix(
                    self.location[1], location_type="N"
                ).toarray()
                self._q = self.current * (qa + qb)
            return self._q


class Pole(BaseSrc):
    """Pole source

    Parameters
    ----------
    receiver_list : list of SimPEG.electromagnetics.static.resistivity.receivers.BaseRx
        A list of DC/IP receivers
    location : (dim) numpy.array_like
        Electrode location
    current : float, default=1.0
        Current amplitude [A]
    """
    def __init__(self, receiver_list=None, location=None, **kwargs):
        super(Pole, self).__init__(receiver_list, location=location, **kwargs)

    def eval(self, sim):
        """Project source to mesh.

        Parameters
        ----------
        sim : SimPEG.electromagnetics.static.resistivity.simulation.BaseDCSimulation
            A DC/IP simulation
        
        Returns
        -------
        np.ndarray
            Discretize source term on the mesh
        """
        if self._q is not None:
            return self._q
        else:
            if sim._formulation == "HJ":
                inds = closest_points_index(sim.mesh, self.location)
                self._q = np.zeros(sim.mesh.nC)
                self._q[inds] = self.current * np.r_[1.0]
            elif sim._formulation == "EB":
                q = sim.mesh.get_interpolation_matrix(self.location, locType="N")
                self._q = self.current * q.toarray()
            return self._q

    @property
    def location_a(self):
        """Location of the A electrode

        Returns
        -------
        (dim) numpy.ndarray
            Location of the A-electrode
        """
        return self.location

    @property
    def location_b(self):
        """Location of the B electrode

        Returns
        -------
        (dim) numpy.ndarray of np.nan
            Location of the B-electrode.
        """
        return np.nan * np.ones_like(self.location)
