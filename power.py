from sys import argv
from sys import stdout
from sys import stderr
import logging
import warnings

logging.basicConfig(level=logging.DEBUG)

import numpy
import nbodykit
from nbodykit import plugins
from nbodykit.utils.pluginargparse import PluginArgumentParser
#--------------------------------------------------
# setup the parser
#--------------------------------------------------

# initialize the parser
parser = PluginArgumentParser("Parallel Power Spectrum Calculator",
        loader=plugins.load,
        description=
     """Calculating matter power spectrum from RunPB input files. 
        Output is written to stdout, in Mpc/h units. 
        PowerSpectrum is the true one, without (2 pi) ** 3 factor. (differ from Gadget/NGenIC internal)
        This script moves all particles to the halo center.
     """,
        epilog=
     """
        This script is written by Yu Feng, as part of `nbodykit'. 
        Other contributors are: Nick Hand, Man-yat Chu
        The author would like thank Marcel Schmittfull for the explanation on cic, shotnoise, and k==0 plane errors.
     """
     )

# add the positional arguments
parser.add_argument("mode", choices=["2d", "1d"]) 
parser.add_argument("Nmesh", type=int, help='size of calculation mesh, recommend 2 * Ngrid')
parser.add_argument("output", help='write power to this file. set as `-` for stdout') 

# add the input field types
h = "one or two input fields, specified as:\n\n"
parser.add_argument("inputs", nargs="+", type=plugins.DataSource.open, 
                    help=h+plugins.DataSource.format_help())

# add the optional arguments
parser.add_argument("--bunchsize", type=int, default=1024*1024*4,
    help='Number of particles to read per rank. A larger number usually means faster IO, but less memory for the FFT mesh. This is not respected by some data sources.')
parser.add_argument("--binshift", type=float, default=0.0,
        help='Shift the bin center by this fraction of the bin width. Default is 0.0. Marcel uses 0.5. this shall rarely be changed.' )
parser.add_argument("--remove-cic", default='anisotropic', choices=["anisotropic","isotropic", "none"],
        help='deconvolve cic, anisotropic is the proper way, see http://www.personal.psu.edu/duj13/dissertation/djeong_diss.pdf')
parser.add_argument("--remove-shotnoise", action='store_true', default=False,
        help='Remove shotnoise')
parser.add_argument("--Nmu", type=int, default=5,
        help='the number of mu bins to use; if `mode = 1d`, then `Nmu` is set to 1' )
parser.add_argument("--los", choices="xyz", default='z',
        help="the line-of-sight direction, which the angle `mu` is defined with respect to")
parser.add_argument("--dk", type=float,
        help='the spacing of k bins to use; if not provided, the fundamental mode of the box is used')
parser.add_argument("--kmin", type=float, default=0,
        help='the edge of the first bin to use; default is 0')
parser.add_argument("-l", "--multipoles", type=lambda x: map(int, x.split()),
        help='compute the power multipoles specified by these `ell` values, i.e., `-l=0` is the monopole')

# parse
ns = parser.parse_args()

#--------------------------------------------------
# done with the parser. now do the real calculation
#--------------------------------------------------

from nbodykit.measurepower import measurepower, measurepoles
from pypm.particlemesh import ParticleMesh
from pypm.transfer import TransferFunction
from mpi4py import MPI

def AnisotropicCIC(comm, complex, w):
    for wi in w:
        tmp = (1 - 2. / 3 * numpy.sin(0.5 * wi) ** 2) ** 0.5
        complex[:] /= tmp

def IsotropicCIC(comm, complex, w):
    for row in range(complex.shape[0]):
        scratch = numpy.float64(w[0][row] ** 2)
        for wi in w[1:]:
            scratch = scratch + wi[0] ** 2

        tmp = (1.0 - 0.666666667 * numpy.sin(scratch * 0.5) ** 2) ** 0.5
        complex[row] *= tmp

def main():

    if MPI.COMM_WORLD.rank == 0:
        print 'importing done'

    chain = [
        TransferFunction.NormalizeDC,
        TransferFunction.RemoveDC,
    ]

    if ns.remove_cic == 'anisotropic':
        chain.append(AnisotropicCIC)
    if ns.remove_cic == 'isotropic':
        chain.append(IsotropicCIC)
        
    # setup the particle mesh object, taking BoxSize from the painters
    pm = ParticleMesh(ns.inputs[0].BoxSize, ns.Nmesh, dtype='f4')

    # paint first input
    Ntot1 = paint(ns.inputs[0], pm)

    # painting
    if MPI.COMM_WORLD.rank == 0:
        print 'painting done'
    pm.r2c()
    if MPI.COMM_WORLD.rank == 0:
        print 'r2c done'

    # filter the field 
    pm.transfer(chain)

    # do the cross power
    do_cross = len(ns.inputs) > 1 and ns.inputs[0] != ns.inputs[1]

    if do_cross:
        
        # crash if box size isn't the same
        if not numpy.all(ns.inputs[0].BoxSize == ns.inputs[1].BoxSize):
            raise ValueError("mismatch in box sizes for cross power measurement")
        
        c1 = pm.complex.copy()
        Ntot2 = paint(ns.inputs[1], pm)

        if MPI.COMM_WORLD.rank == 0:
            print 'painting 2 done'

        pm.r2c()
        if MPI.COMM_WORLD.rank == 0:
            print 'r2c 2 done'

        # filter the field 
        pm.transfer(chain)
        c2 = pm.complex
  
    # do the auto power
    else:
        c1 = pm.complex
        c2 = pm.complex
        Ntot2 = Ntot1 

    if ns.remove_shotnoise and not do_cross:
        shotnoise =  pm.BoxSize.prod() / (1.0*Ntot1)
    else:
        shotnoise = 0
 
    # only need one mu bin if 1d case is requested
    if ns.mode == "1d": ns.Nmu = 1 

    # store some meta data
    Lx, Ly, Lz = pm.BoxSize
    meta = {'Lx':Lx, 'Ly':Ly, 'Lz':Lz, 'volume':Lx*Ly*Lz, 
            'N1':Ntot1, 'N2':Ntot2, 'shot_noise': shotnoise}
            
    # measure P(k,mu)
    if ns.multipoles is None:
        result = measurepower(pm, c1, c2, ns.Nmu, binshift=ns.binshift, 
                                shotnoise=shotnoise, los=ns.los, dk=ns.dk, 
                                kmin=ns.kmin)
    # measure multipoles
    else:
        ns.mode = '1d'
        result = measurepoles(pm, c1, c2, ns.multipoles, binshift=ns.binshift, 
                                los=ns.los, dk=ns.dk, kmin=ns.kmin)
    
    
    # format the output appropriately
    if ns.multipoles is not None:
        meta['edges'] = result[-1]
        result = [result[0], result[2]] + list(numpy.squeeze(numpy.split(result[1], len(ns.multipoles), axis=1)))
    elif ns.mode == "1d":
        # this writes out 0 -> mean k, 2 -> mean power, 3 -> number of modes
        meta['edges'] = result[-1][0] # write out kedges as metadata
        result = map(numpy.ravel, (result[i] for i in [0, 2, 3]))
    elif ns.mode == "2d":
        result = dict(zip(['k','mu','power','modes','edges'], result))

    if MPI.COMM_WORLD.rank == 0:
        print 'measure'
        storage = plugins.PowerSpectrumStorage.new(ns.mode, ns.output)
        storage.write(result, **meta)
 
def paint(input, pm):
    # compatibility with the older painters. 
    # We need to get rid of them.
    if hasattr(input, 'paint'):
        if pm.comm.rank == 0:
            warnings.warn('paint method of type %s shall be replaced with a read method'
                % type(input), DeprecationWarning)
        return input.paint(pm)

    pm.real[:] = 0
    Ntot = 0

    if pm.comm.rank == 0: 
        logging.info("BoxSize = %s", str(input.BoxSize))
    for position, weight in input.read(['Position', 'Mass'], pm.comm, ns.bunchsize):
        if len(position) > 0:
            logging.info("position range on rank %d is %s:%s", pm.comm.rank, 
                    position.min(axis=0), position.max(axis=0))
        layout = pm.decompose(position)
        position = layout.exchange(position)
        if weight is None:
            Ntot += len(position)
            weight = 1
        else:
            weight = layout.exchange(weight)
            Ntot += weight.sum()
        pm.paint(position, weight)
    return pm.comm.allreduce(Ntot)

main()
