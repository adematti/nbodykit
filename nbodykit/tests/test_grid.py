from mpi4py_test import MPITest
from nbodykit.lab import *
from nbodykit import setup_logging

import os
import shutil
import numpy
from numpy.testing import assert_array_equal, assert_almost_equal, assert_allclose

setup_logging("debug")

@MPITest([1,4])
def test_linear_grid(comm):
    """
    Compute the power spectrum of a linear density grid and check
    the accuracy of the computed result against the input theory power spectrum
    """
    cosmo = cosmology.Planck15
    CurrentMPIComm.set(comm)

    # linear grid 
    Plin = cosmology.EHPower(cosmo, redshift=0.55)
    source = Source.LinearMesh(Plin, Nmesh=64, BoxSize=512, seed=42)

    # compute P(k) from linear grid
    r = FFTPower(source, mode='1d', Nmesh=64, dk=0.01, kmin=0.005)
    
    # run and get the result
    valid = r.power['modes'] > 0
    
    # variance of each point is 2*P^2/N_modes
    theory = Plin(r.power['k'][valid])
    errs = (2*theory**2/r.power['modes'][valid])**0.5
    
    # compute reduced chi-squared of measurement to theory
    chisq = ((r.power['power'][valid].real - theory)/errs)**2
    N = valid.sum()
    red_chisq = chisq.sum() / (N-1)
    
    # make sure it is less than 1.5 (should be ~1)
    assert red_chisq < 1.5, "reduced chi sq of linear grid measurement = %.3f" %red_chisq

@MPITest([1,4])
def test_bigfile_grid(comm):
    """
    Paint a linear mesh and save it. Then, load the mesh as a 
    :class:`~nbodykit.source.grid.BigFileMesh` and compare to the 
    original mesh object
    """
    import tempfile
    
    cosmo = cosmology.Planck15
    CurrentMPIComm.set(comm)

    # input linear mesh
    Plin = cosmology.EHPower(cosmo, redshift=0.55)
    source = Source.LinearMesh(Plin, BoxSize=512, Nmesh=64, seed=42)
    
    real = source.paint(mode='real')
    complex = source.paint(mode="complex")

    # and save to tmp directory
    if comm.rank == 0: 
        output = tempfile.mkdtemp()
    else:
        output = None
    output = comm.bcast(output)

    real.save(output, dataset='Field')

    # now load it and paint to the algorithm's ParticleMesh
    source = Source.BigFileMesh(path=output, dataset='Field')
    loaded_real = source.paint()
    
    # compare to direct algorithm result
    assert_array_equal(real, loaded_real)
    
    complex.save(output, dataset='FieldC')

    # now load it and paint to the algorithm's ParticleMesh
    source = Source.BigFileMesh(path=output, dataset='FieldC')
    loaded_real = source.paint(mode="complex")
    
    # compare to direct algorithm result
    assert_allclose(complex, loaded_real, rtol=1e-5)
    if comm.rank == 0:
        shutil.rmtree(output)

