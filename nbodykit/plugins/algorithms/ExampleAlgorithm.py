from nbodykit.extensionpoints import Algorithm, DataSource

import numpy
import logging

class Describe(Algorithm):
    plugin_name = "Describe"
    logger = logging.getLogger(plugin_name)

    @classmethod
    def register(kls):
        p = kls.parser
        p.description = "Describe the data source"
        p.add_argument("datasource", type=DataSource.fromstring)
        p.add_argument("--column", default='Position')
     
    def finalize_attributes(self):
        pass

    def run(self):
        """
        Run the algorithm, which does nothing
        """
        stats = {}
        left = []
        right = []
        for pos, in self.datasource.read([self.column], stats):
            left.append(numpy.min(pos, axis=0))
            right.append(numpy.max(pos, axis=0))
        left = numpy.min(left, axis=0)
        right = numpy.max(right, axis=0)
        left = numpy.min(self.comm.allgather(left), axis=0)
        right = numpy.max(self.comm.allgather(right), axis=0)
        return left, right

    def save(self, output, data):
        left, right = data
        if self.comm.rank == 0:
            template = "DataSource %s Column %s : min = %s max = %s\n"
            if output == '-':
                import sys
                output = sys.stdout
            else:
                output = file(output, 'w')
            output.write(template % 
                (self.datasource, self.column, str(left), str(right)))
