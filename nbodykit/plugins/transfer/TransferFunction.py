from nbodykit.extensionpoints import Transfer
import numpy

class AnisotropicCIC(Transfer):
    """
    Divide by a kernel in Fourier space to account for
    the convolution of the gridded quantity with the 
    cloud-in-cell window function in configuration space
    """
    plugin_name = "AnisotropicCIC"

    @classmethod
    def register(kls):
        pass

    def __call__(self, pm, complex):
        for wi in pm.w:
            tmp = (1 - 2. / 3 * numpy.sin(0.5 * wi) ** 2) ** 0.5
            complex[:] /= tmp
            
            
class NormalizeDC(Transfer):
    """
    Removes the DC amplitude in Fourier space, which effectively
    divides by the mean in configuration space
    """
    plugin_name = "NormalizeDC"

    @classmethod
    def register(kls):
        pass

    def __call__(self, pm, complex):
        ind = []
        value = 0.
        found = True
        for wi in pm.w:
            if (wi != 0).all():
                found = False
                break
            ind.append((wi == 0).nonzero()[0][0])
        if found:
            ind = tuple(ind)
            value = numpy.abs(complex[ind])
        value = pm.comm.allreduce(value)
        complex[:] /= value
        
class RemoveDC(Transfer):
    """
    Remove the DC amplitude, which sets the mean of the 
    field in configuration space to zero
    """
    plugin_name = "RemoveDC"

    @classmethod
    def register(kls):
        pass

    def __call__(self, pm, complex):
        ind = []
        for wi in pm.w:
            if (wi != 0).all():
                return
            ind.append((wi == 0).nonzero()[0][0])
        ind = tuple(ind)
        complex[ind] = 0.
            


        
            
