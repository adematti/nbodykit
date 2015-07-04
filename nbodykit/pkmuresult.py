import numpy as np
import numpy.ma.mrecords as mrecords

def rebin(index, edges, data, weights):
    """
    Rebin data stored in a masked recarray, using the edges specified
    
    Parameters
    ----------
    index : list of ndarrays
        A list of arrays specifying the bin centers. The length should
        be the number of bin dimensions
    edges : list of arrays
        A list of arrays specifying the bin edges in each dimension
    data : numpy.ma.mrecords.MaskedRecords
        Masked recarray with each field representing a data column
        to be re-binned. Masked elements will not contribute to the
        re-binned results
    weights : array_like
        The weights to use when re-binning. Must have the same shape
        as `data`
        
    """
    if data.shape != weights.shape:
        raise ValueError("data and weights do not have same shape in rebin")
        
    toret = {}
    
    # digitize each index
    dig = []
    ndims = []
    for i in range(len(index)):
        dig.append(np.digitize(index[i].flat, edges[i]))
        ndims.append(len(edges[i])+1)
        
    # make the multi index for tracking flat indices
    multi_index = np.ravel_multi_index(dig, ndims)
    
    # loop over each field in the recarray
    names = data.dtype.names
    for name in names:
        
        inds = ~data[name].mask
        mi = multi_index[inds.flatten()]
        
        # first count values in each bin
        N = np.bincount(mi, weights=weights[inds], minlength=ndims[0]*ndims[1])
        
        # now sum the data columns
        valsum = np.bincount(mi, weights=data[name][inds]*weights[inds], minlength=ndims[0]*ndims[1])
        
        # ignore warnings -- want N == 0 to be set as NaNs
        with np.errstate(invalid='ignore'):
            toret[name] = (valsum / N).reshape(ndims)[1:-1, 1:-1]
        
    return toret


class PkmuResult(object):
    """
    PkmuResult provides an interface to store and manipulate a 2D power 
    spectrum measurement, as a function of wavenumber `k` and line-of-sight
    angle `mu`. 
    
    Notes
    -----
    The `data` attribute can be accessed using the __getitem__ behavior
    of `PkmuResult`. Additionally, __getitem__ can be passed `k` and `mu`
    values, which can refer to the bin center values. If 
    `force_index_match = True`, then these values will automatically 
    match the nearest bin center value
    
    Attributes
    ----------
    data    : :py:class:`numpy.ma.mrecords.MaskedRecords`
        a masked structured array holding the data, where masked
        elements represent (k,mu) bins with missing data
    index   : :py:class:`numpy.rec.recarray`
        a recarray with field names `k_center`, `mu_center` that
        stores the center bin values. Same shape as `data`
    Nk      : int
        the number of k bins
    Nmu     : int
        the number of mu bins
    columns : list of str
        a list of the names of the fields in `data`
    kedges  : array_like
        the edges of the k bins used. shape is `Nk+1`
    muedges : array_like
        the edges of the mu bins used. shape is `Nmu+1`
    force_index_match : bool
         If `True`, when indexing using `k` or `mu` values, return
         results for the nearest bin to the value specified
    """
    def __init__(self, kedges, muedges, data, force_index_match=False, **kwargs):
        """
        Parameters
        ----------
        kedges : array_like
            The list of the edges of the k bins
        muedges : array_like
            The list of the edges of the mu bins
        data : dict
            Dictionary holding 2D arrays of data. The keys
            will be used to infer the field names in the
            resulting np.recarray
        force_index_match : bool
             If `True`, when indexing using `k` or `mu` values, return
             results for the nearest bin to the value specified
        **kwargs
            Any additional metadata for the power spectrum object can
            be passed as keyword arguments here
        """
        # name of the columns
        self.columns = data.keys()
        self.kedges = kedges
        self.muedges = muedges
        
        # treat any NaNs as missing data
        mask = np.zeros((len(kedges)-1, len(muedges)-1), dtype=bool)
        for name in self.columns:
            mask = np.logical_or(mask, ~np.isfinite(data[name]))

        # make a masked recarray to store the data
        self.data = np.rec.fromarrays(data.values(), names=self.columns)
        self.data = np.ma.array(self.data, mask=mask).view(mrecords.mrecarray)
        
        # now store the cente (k,mu) of each bin as the index
        k_center = 0.5*(kedges[1:]+kedges[:-1])[...,None]
        mu_center = 0.5*(muedges[1:]+muedges[:-1])[None,...]
        self.index = np.rec.fromarrays(np.broadcast_arrays(k_center,mu_center), 
                                        names=['k_center', 'mu_center'])
               
        # match closest index always returns nearest bin value                         
        self.force_index_match = force_index_match
        
        # save any metadata too
        self._metadata = []
        for k, v in kwargs.iteritems():
            self._metadata.append(k)
            setattr(self, k, v)
    
    def __getitem__(self, key):
        try:
            new_key = ()
            
            # if tuple, check if we need to replace values with integers
            if isinstance(key, tuple):
                if len(key) != 2:
                    raise IndexError("too many indices for array")
                
                for i, subkey in enumerate(key):
                    if isinstance(subkey, slice):
                        new_slice = []
                        for name in ['start', 'stop']:
                            val = getattr(subkey, name)
                            if not isinstance(val, int) and val is not None:
                                new_slice.append(self._get_index(i,val))
                            else:
                                new_slice.append(val)
                        new_key += (slice(*new_slice),)
                    elif not isinstance(subkey, int):
                        new_key += (self._get_index(i,subkey),)
                    else:
                        new_key += (subkey,)
                key = new_key            
                            
            return self.data[key]
        except Exception as e:
            raise KeyError("Key not understood in __getitem__: %s" %(str(e)))
    
    def __getattr__(self, key):
        if key in self.columns:
            return self.data[key]
        else:
            return object.__getattr__(key)
    
    def to_pickle(self, filename):
        import pickle
        pickle.dump(self.__dict__, open(filename, 'w'))
        
    @classmethod
    def from_pickle(cls, filename):
        import pickle
        d = pickle.load(open(filename, 'r'))
        data = {name : d['data'][name].data for name in d['columns']}
        kwargs = {k:d[k] for k in d['_metadata']}
        return PkmuResult(d['kedges'], d['muedges'], data, d['force_index_match'], **kwargs)
    
    #--------------------------------------------------------------------------
    # convenience properties
    #--------------------------------------------------------------------------
    @property
    def k_center(self):
        return self.index.k_center[:,0]
    
    @property
    def mu_center(self):
        return self.index.mu_center[0,:]
    
    @property
    def Nmu(self):
        return self.data.shape[1]
        
    @property
    def Nk(self):
        return self.data.shape[0]
        
    #--------------------------------------------------------------------------
    # utility functions
    #--------------------------------------------------------------------------
    def _get_index(self, name, val):

        index = self.k_center
        if name == 'mu' or name == 1:
            index = self.mu_center

        if self.force_index_match:
            i = (np.abs(index-val)).argmin()
        else:
            try:
                i = list(index).index(val)
            except Exception as e:
                raise IndexError("error converting %s index; try setting " %name + 
                                 "`force_index_match=True`: %s" %str(e))
                
        return i
            
    def _reindex(self, i, index, edges, bins, weights):
        
        # compute the bins
        N_old = index[i].shape[i]
        if isinstance(bins, int):
            if bins >= N_old:
                raise ValueError("Can only reindex into fewer than %d bins" %N_old)
            bins = np.linspace(edges[i][0], edges[i][-1], bins+1)
        else:
            if len(bins) >= N_old:
                raise ValueError("Can only reindex into fewer than %d bins" %N_old)
        
        # compute the weights
        if weights is None:
            weights = np.ones((self.Nk, self.Nmu))
        else:
            if isinstance(weights, basestring):
                if weights not in self.columns:
                    raise ValueError("Cannot weight by `%s`; no such column" %weights)
                weights = self.data[weights].data
            
        # get the rebinned data
        edges[i] = bins
        new_data = rebin(index, edges, self.data, weights)
        
        # return a new PkmuResult
        return PkmuResult(edges[0], edges[1], new_data, self.force_index_match)
        
    #--------------------------------------------------------------------------
    # main functions
    #--------------------------------------------------------------------------
    def nearest_bin_center(self, name, val):
        """
        Return the nearest `k` or `mu` bin center value to the value `val`
        
        Parameters
        ----------
        name : int or string
            If an int is passed, must be `0` for `k` or `1` for `mu`. If 
            a string is passed, must be either `k` or `mu` 
        val : float
            The `k` or `mu` value that we want to find the nearest bin to
            
        Returns
        -------
        index_val : float
            The center value of the bin closest to `val`
        """
        
        # verify input
        if isinstance(name, basestring):
            if name not in ['k','mu']:
                raise ValueError("`name` argument must be `k` or `mu`, if string")
        elif isinstance(name, int):
            if name not in [0, 1]:
                raise ValueError("`name` argument must be 0 for `k` or 1 for `mu`, if int")
        else:
            raise ValueError("`name` argument must be an int or string")
        
        index = self.k_center
        if name == 'mu' or name == 1:
            index = self.mu_center

        i = (np.abs(index-val)).argmin()
        return index[i]
        
    def Pk(self, mu):
        """
        Return the power measured P(k) at a specific value of mu, as a 
        masked numpy recarray. 
        
        Notes
        -----
        *   `mu` can be either an integer specifying which bin, or the
            center value of the bin itself. 
        *   If `mu` gives the bin value and `force_index_match` is 
            False, then the value must be present in `mu_center`. If 
            `force_index_match` is True, then it returns the nearest 
            bin to the value specified
        
        Parameters
        ---------
        mu : int or float
            The mu bin to select. If a `float`, `mu` must be a value 
            in `self.mu_center`.
            
        Returns
        -------
        Pk : numpy.ma.mrecords.MaskedRecords
            A masked recarray specifying the P(k) slice at the mu-bin specified
        """
        if not isinstance(mu, int): 
            mu = self._get_index('mu', mu)
        
        return self.data[:,mu]
        
    def Pmu(self, k):
        """
        Return the power measured P(mu) at a specific value of k, as a 
        masked numpy recarray. 
        
        Notes
        -----
        *   `k` can be either an integer specifying which bin, or the
            center value of the bin itself. 
        *   If `k` gives the bin value and `force_index_match` is 
            False, then the value must be present in `k_center`. If 
            `force_index_match` is True, then it returns the nearest 
            bin to the value specified
        
        Parameters
        ---------
        k : int or float
            The k bin to select. If a `float`, `k` must be a value 
            in `self.k_center`.
            
        Returns
        -------
        Pmu : numpy.ma.mrecords.MaskedRecords
            A masked recarray specifying the P(mu) slice at the k-bin specified
        """
        if not isinstance(k, int): 
            k = self._get_index('k', k)
        
        return self.data[k,:]
        
    def reindex_mu(self, bins, weights=None):
        """
        Reindex the mu dimension and return a PkmuResult holding
        the re-binned data, optionally weighted by `weights`
        
        
        Parameters
        ---------
        bins : integer or array_like
            If an integer is given, `bins+1` edges are used. If a sequence,
            then the values should specify the bin edges.
        weights : str or array_like, optional
            If a string is given, it is intepreted as the name of a 
            data column in `self.data`. If a sequence is passed, then the
            shape must be equal to (`self.Nk`, `self.Nmu`)
            
        Returns
        -------
        pkmu : PkmuResult
            class holding the re-binned results
        """
        index = [self.index.k_center, self.index.mu_center]
        edges = [self.kedges, self.muedges]
        return self._reindex(1, index, edges, bins, weights)
    
    def reindex_k(self, bins, weights=None):
        """
        Reindex the k dimension and return a PkmuResult holding
        the re-binned data, optionally weighted by `weights`
        
        
        Parameters
        ---------
        bins : integer or array_like
            If an integer is given, `bins+1` edges are used. If a sequence,
            then the values should specify the bin edges.
        weights : str or array_like, optional
            If a string is given, it is intepreted as the name of a 
            data column in `self.data`. If a sequence is passed, then the
            shape must be equal to (`self.Nk`, `self.Nmu`)
            
        Returns
        -------
        pkmu : PkmuResult
            class holding the re-binned results
        """
        index = [self.index.k_center, self.index.mu_center]
        edges = [self.kedges, self.muedges]
        return self._reindex(0, index, edges, bins, weights)
        
    
    
            
        