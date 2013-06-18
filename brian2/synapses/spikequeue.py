"""
The spike queue class stores future synaptic events
produced by a given presynaptic neuron group (or postsynaptic for backward
propagation in STDP).
"""
import numpy as np

from brian2.units.stdunits import ms
from brian2.utils.logger import get_logger

__all__=['SpikeQueue']

logger = get_logger(__name__)

INITIAL_MAXSPIKESPER_DT = 1

class SpikeQueue(object):
    '''
    Data structure saving the spikes and taking care of delays.
    
    Parameters
    ----------

    synapses : list of ndarray 
        A list of synapses (synapses[i]=array of synapse indices for neuron i).
    delays : ndarray
        An array of delays (delays[k]=delay of synapse k).
    dt : `Quantity`
        The timestep of the source group
    max_delay : `Quantity`, optional
        The maximum delay (in second) of synaptic events. At run time, the
        structure is resized to the maximum delay in `delays`, and thus
        the `max_delay` should only be specified if delays can change
        during the simulation (in which case offsets should not be
        precomputed).
    precompute_offsets : bool, optional
        A flag to precompute offsets. Defaults to ``True``, i.e. offsets (an
        internal array derived from `delays`, used to insert events in the data
        structure, see below) are precomputed for all neurons when the object
        is prepared with the `compress` method. This usually results in a speed
        up but takes memory, which is why it can be disabled.

    Notes
    -----

    **Data structure** 
    
    A spike queue is implemented as a 2D array `X` that is circular in the time
    direction (rows) and dynamic in the events direction (columns). The
    row index corresponding to the current timestep is `currentime`.
    Each element contains the target synapse index.    
    
    **Offsets**
    
    Offsets are used to solve the problem of inserting multiple synaptic events
    with the same delay. This is difficult to vectorise. If there are n synaptic
    events with the same delay, these events are given an offset between 0 and
    n-1, corresponding to their relative position in the data structure.
    They can be either precalculated (faster), or determined at run time
    (saves memory). Note that if they are determined at run time, then it is
    possible to also vectorise over presynaptic spikes.
    '''
    
    def __init__(self, synapses, delays, dt, max_delay = 0*ms,
                 precompute_offsets = True):
        #: Reference to the synaptic delays
        self.delays = delays
        #: Reference to the synaptic indices
        self.synapses = synapses
        #: Whether the offsets should be precomputed
        self._precompute_offsets=precompute_offsets
        
        self._max_delay=max_delay
        if max_delay>0: # do not precompute offsets if delays can change
            self._precompute_offsets=False
        
        # number of time steps, maximum number of spikes per time step
        nsteps = int(np.floor((max_delay)/(dt)))+1
        #: The main data structure
        self.X = np.zeros((nsteps, INITIAL_MAXSPIKESPER_DT),
                          dtype=self.synapses[0].dtype) # target synapses
        self.X_flat = self.X.reshape(nsteps*INITIAL_MAXSPIKESPER_DT, )
        #: The current time (in time steps)
        self.currenttime = 0
        #: number of events in each time step
        self.n = np.zeros(nsteps, dtype = int) # 
        #: precalculated offsets
        self._offsets = None

        
    def compress(self):
        '''
        Prepare the data structure and pre-compute offsets.
        This is called every time the network is run. The size of the
        of the data structure (number of rows) is adjusted to fit the maximum
        delay in `delays`, if necessary. Offsets are calculated, unless
        the option `precompute_offsets` is set to ``False``. A flag is set if
        delays are homogeneous, in which case insertion will use a faster method
        implemented in `insert_homogeneous`.        
        '''
        if self.delays:
            max_delays = max(self.delays)
            min_delays = min(self.delays)
        else:
            max_delays = min_delays = 0
        
        nsteps = max_delays + 1
        # Check whether some delays are too long
        if (self._max_delay>0) and (nsteps>self.X.shape[0]):
            raise ValueError,"Synaptic delays exceed maximum delay"
        
        # Adjust the maximum delay and number of events per timestep if necessary
        maxevents=self.X.shape[1]
        if maxevents==INITIAL_MAXSPIKESPER_DT: # automatic resize
            maxevents=max(INITIAL_MAXSPIKESPER_DT,max([len(targets) for targets in self.synapses]))
        # Check if delays are homogeneous
        if self._max_delay>0:
            self._homogeneous=False
        else:
            self._homogeneous=(nsteps==min_delays + 1)
        # Resize
        if (nsteps>self.X.shape[0]) or (maxevents>self.X.shape[1]): # Resize
            nsteps=max(nsteps,self.X.shape[0]) # Choose max_delay if is is larger than the maximum delay
            maxevents=max(maxevents,self.X.shape[1])
            self.X = np.zeros((nsteps, maxevents), dtype = self.synapses[0].dtype) # target synapses
            self.X_flat = self.X.reshape(nsteps*maxevents,)
            self.n = np.zeros(nsteps, dtype = int) # number of events in each time step

        # Precompute offsets
        if self._precompute_offsets:
            self.precompute_offsets()

    ################################ SPIKE QUEUE DATASTRUCTURE ################
    def next(self):
        '''
        Advances by one timestep
        '''
        self.n[self.currenttime]=0 # erase
        self.currenttime=(self.currenttime+1) % len(self.n)
        
    def peek(self):
        '''
        Returns the all the synaptic events corresponding to the current time,
        as an array of synapse indexes.
        '''      
        return self.X[self.currenttime,:self.n[self.currenttime]]    
    
    def precompute_offsets(self):
        '''
        Precompute all offsets corresponding to delays. This assumes that
        delays will not change during the simulation.
        '''
        self._offsets = []
        for i in xrange(len(self.synapses)):
            delays = self.delays[self.synapses[i][:]]
            self._offsets.append(self.offsets(delays))
    
    def offsets(self, delay):
        '''
        Calculates offsets corresponding to a delay array.
        If there n identical delays, there are given offsets between
        0 and n-1.
        Example:
        
            [7,5,7,3,7,5] -> [0,0,1,0,2,1]
            
        The code is complex because tricks are needed for vectorisation.
        '''
        # We use merge sort because it preserves the input order of equal
        # elements in the sorted output
        I = np.argsort(delay, kind='mergesort')
        xs = delay[I]
        J = xs[1:]!=xs[:-1]
        A = np.hstack((0, np.cumsum(J)))
        B = np.hstack((0, np.cumsum(-J)))
        BJ = np.hstack((0, B[J]))
        ei = B-BJ[A]
        ofs = np.zeros_like(delay)
        ofs[I] = np.array(ei,dtype=ofs.dtype) # maybe types should be signed?
        return ofs
           
    def insert(self, delay, target, offset=None):
        '''
        Vectorised insertion of spike events.
        
        Parameters
        ----------
        
        delay : ndarray
            Delays in timesteps.
            
        target : ndarray
            Target synaptic indices.
            
        offset : ndarray
            Offsets within timestep. If unspecified, they are calculated
            from the delay array.
        '''
        delay = np.array(delay, dtype=int)

        if offset is None:
            offset = self.offsets(delay)
        
        # Calculate row indices in the data structure
        timesteps = (self.currenttime + delay) % len(self.n)
        # (Over)estimate the number of events to be stored, to resize the array
        # It's an overestimation for the current time, but I believe a good one
        # for future events
        m = max(self.n) + len(target)
        if (m >= self.X.shape[1]): # overflow
            self.resize(m+1)
        
        self.X_flat[timesteps*self.X.shape[1]+offset+self.n[timesteps]] = target
        self.n[timesteps] += offset+1 # that's a trick (to update stack size)
        # Note: the trick can only work if offsets are ordered in the right way
        
    def insert_homogeneous(self, delay, target):
        '''
        Inserts events at a fixed delay.
        
        Parameters
        ----------
        delay : int
            Delay in timesteps.
            
        target : ndarray
            Target synaptic indices.
        '''
        timestep = (self.currenttime + delay) % len(self.n)
        nevents = len(target)
        m = self.n[timestep]+nevents+1 # If overflow, then at least one self.n is bigger than the size
        if (m >= self.X.shape[1]):
            self.resize(m+1) # was m previously (not enough)
        k=timestep*self.X.shape[1]+self.n[timestep]
        self.X_flat[k:k+nevents] = target
        self.n[timestep] += nevents
        
    def resize(self, maxevents):
        '''
        Resizes the underlying data structure (number of columns = spikes per
        dt).
        
        Parameters
        ----------
        maxevents : int
            The new number of columns. It will be rounded to the closest power
            of 2.
        '''
        # old and new sizes
        old_maxevents = self.X.shape[1]
        new_maxevents = int(2**np.ceil(np.log2(maxevents))) # maybe 2 is too large
        # new array
        newX = np.zeros((self.X.shape[0], new_maxevents), dtype = self.X.dtype)
        newX[:, :old_maxevents] = self.X[:, :old_maxevents] # copy old data
        
        self.X = newX
        self.X_flat = self.X.reshape(self.X.shape[0]*new_maxevents,)
        
    def push(self, spikes):
        '''
        Push spikes to the queue.
        
        Parameters
        ----------
        spikes : iterable of int
            A list/array of indices, denoting the spiking neurons.
        '''
        if len(spikes):
            if self._homogeneous: # homogeneous delays
                synaptic_events = np.hstack([self.synapses[i][:] for i in spikes]) # could be not efficient
                self.insert_homogeneous(self.delays[0], synaptic_events)
            elif self._offsets is None: # vectorise over synaptic events
                # there are no precomputed offsets, this is the case (in particular) when there are dynamic delays
                synaptic_events = np.hstack([self.synapses[i][:] for i in spikes])
                if len(synaptic_events):
                    delay = self.delays[synaptic_events]
                    self.insert(delay, synaptic_events)
            else: # offsets are precomputed
                for i in spikes:
                    synaptic_events=self.synapses[i][:]    
                    if len(synaptic_events):
                        delay = self.delays[synaptic_events]
                        offsets = self._offsets[i]
                        self.insert(delay, synaptic_events, offsets)