from __future__ import print_function
import unittest
import numpy as np
import SimPEG.electromagnetics.frequency_domain as fdem
from SimPEG import *
from discretize import TensorMesh
from pymatsolver import PardisoSolver

np.random.seed(41)


class STITCHED_EM1D_FD_Jacobian_Test_MagDipole(unittest.TestCase):

    def setUp(self, parallel=False):

        dz = 1
        geometric_factor = 1.1
        n_layer = 20
        thicknesses = dz * geometric_factor ** np.arange(n_layer-1)

        frequencies = np.array([900, 7200, 56000], dtype=float)
        n_sounding = 50
        dx = 20.
        hx = np.ones(n_sounding) * dx
        hz = np.r_[thicknesses, thicknesses[-1]]

        mesh = TensorMesh([hx, hz], x0='00')

        x = mesh.cell_centers_x
        y = np.zeros_like(x)
        z = np.ones_like(x) * 30.
        receiver_locations = np.c_[x+8., y, z]
        source_locations = np.c_[x, y, z]
        topo = np.c_[x, y, z-30.].astype(float)

        sigma_map = maps.ExpMap(mesh)

        source_list = []

        for i_sounding in range(0, n_sounding):

            source_location = mkvc(source_locations[i_sounding, :])
            receiver_location = mkvc(receiver_locations[i_sounding, :])
            receiver_list = []
            receiver_list.append(
                fdem.receivers.PointMagneticFieldSecondary(
                    receiver_location,
                    orientation="z",
                    component="both"
                )
            )

            for i_freq, frequency in enumerate(frequencies):
                src = fdem.sources.MagDipole(
                    receiver_list, frequency, source_location,
                    orientation="z", i_sounding=i_sounding
                )
                source_list.append(src)

        survey = fdem.Survey(source_list)

        simulation = fdem.Simulation1DLayeredStitched(
            survey=survey, thicknesses=thicknesses, sigmaMap=sigma_map,
            topo=topo, parallel=parallel, n_cpu=2, verbose=False
        )
        self.sim = simulation
        self.mesh = mesh

    def test_EM1DFDJvec_Layers(self):
        # Conductivity
        inds = self.mesh.cell_centers[:, 1] < 25
        inds_1 = self.mesh.cell_centers[:, 1] < 50
        sigma = np.ones(self.mesh.n_cells) * 1./100.
        sigma[inds_1] = 1./10.
        sigma[inds] = 1./50.
        sigma_em1d = sigma.reshape(self.mesh.vnC, order='F').flatten()
        m_stitched = np.log(sigma_em1d)

        def fwdfun(m):
            resp = self.sim.dpred(m)
            return resp
            # return Hz

        def jacfun(m, dm):
            Jvec = self.sim.Jvec(m, dm)
            return Jvec

        def derChk(m):
            return [fwdfun(m), lambda mx: jacfun(m, mx)]

        dm = m_stitched * 0.5

        passed = tests.check_derivative(
            derChk, m_stitched, num=4, dx=dm, plotIt=False, eps=1e-15
        )
        self.assertTrue(passed)
        if passed:
            print("STITCHED EM1DFM MagDipole Jvec test works")

    def test_EM1DFDJtvec_Layers(self):
        # Conductivity
        inds = self.mesh.cell_centers[:, 1] < 25
        inds_1 = self.mesh.cell_centers[:, 1] < 50
        sigma = np.ones(self.mesh.n_cells) * 1./100.
        sigma[inds_1] = 1./10.
        sigma[inds] = 1./50.
        sigma_em1d = sigma.reshape(self.mesh.vnC, order='F').flatten()
        m_stitched = np.log(sigma_em1d)

        dobs = self.sim.dpred(m_stitched)

        m_ini = np.log(1./100.) * np.ones(self.mesh.n_cells)
        resp_ini = self.sim.dpred(m_ini)
        dr = resp_ini - dobs

        def misfit(m, dobs):
            dpred = self.sim.dpred(m)
            misfit = 0.5 * np.linalg.norm(dpred - dobs) ** 2
            dmisfit = self.sim.Jtvec(m, dr)
            return misfit, dmisfit

        def derChk(m):
            return misfit(m, dobs)

        passed = tests.check_derivative(derChk, m_ini, num=4, plotIt=False, eps=1e-27)
        self.assertTrue(passed)
        if passed:
            print("STITCHED EM1DFM MagDipole Jtvec test works")

if __name__ == '__main__':
    unittest.main()