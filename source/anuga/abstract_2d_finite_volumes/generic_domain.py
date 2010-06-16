"""Class Domain - 2D triangular domains for finite-volume computations of
   conservation laws.
   
   This is the base class for various domain models, such as: the Advection
   implementation is a simple algorithm, mainly for testing purposes, and
   the standard Shallow Water Wave domain (simply known as Domain) is the
   standard for realistic simulation.


   Copyright 2004
   Ole Nielsen, Stephen Roberts, Duncan Gray
   Geoscience Australia
"""

import types
from time import time as walltime

from anuga.abstract_2d_finite_volumes.neighbour_mesh import Mesh
from pmesh2domain import pmesh_to_domain
from region import Set_region as region_set_region
from anuga.geometry.polygon import inside_polygon
from anuga.abstract_2d_finite_volumes.util import get_textual_float
from quantity import Quantity
import anuga.utilities.log as log

import numpy as num

class Generic_Domain:
    '''
    Generic computational Domain constructor.
    # @param source Name of mesh file or coords of mesh vertices.
    # @param triangles Mesh connectivity (see mesh.py for more information).
    # @param boundary (see mesh.py for more information)
    # @param conserved_quantities List of names of quantities to be conserved.
    # @param other_quantities List of names of other quantities.
    # @param tagged_elements ??
    # @param geo_reference ??
    # @param use_inscribed_circle ??
    # @param mesh_filename ??
    # @param use_cache ??
    # @param verbose True if this method is to be verbose.
    # @param full_send_dict ??
    # @param ghost_recv_dict ??
    # @param processor ??
    # @param numproc ??
    # @param number_of_full_nodes ??
    # @param number_of_full_triangles ??    
    '''

    def __init__(self, source=None,
                       triangles=None,
                       boundary=None,
                       conserved_quantities=None,
                       evolved_quantities=None,
                       other_quantities=None,
                       tagged_elements=None,
                       geo_reference=None,
                       use_inscribed_circle=False,
                       mesh_filename=None,
                       use_cache=False,
                       verbose=False,
                       full_send_dict=None,
                       ghost_recv_dict=None,
                       processor=0,
                       numproc=1,
                       number_of_full_nodes=None,
                       number_of_full_triangles=None):

        """Instantiate generic computational Domain.

        Input:
          source:    Either a mesh filename or coordinates of mesh vertices.
                     If it is a filename values specified for triangles will
                     be overridden.
          triangles: Mesh connectivity (see mesh.py for more information)
          boundary:  See mesh.py for more information

          conserved_quantities: List of quantity names entering the
                                conservation equations
          evolved_quantities:   List of all quantities that evolve
          other_quantities:     List of other quantity names

          tagged_elements:
          ...
        """

        number_of_full_nodes=None
        number_of_full_triangles=None
        
        # Determine whether source is a mesh filename or coordinates
        if type(source) == types.StringType:
            mesh_filename = source
        else:
            coordinates = source

        # In case a filename has been specified, extract content
        if mesh_filename is not None:
            coordinates, triangles, boundary, vertex_quantity_dict, \
                         tagged_elements, geo_reference = \
                         pmesh_to_domain(file_name=mesh_filename,
                                         use_cache=use_cache,
                                         verbose=verbose)

        # Initialise underlying mesh structure
        self.mesh = Mesh(coordinates, triangles,
                         boundary=boundary,
                         tagged_elements=tagged_elements,
                         geo_reference=geo_reference,
                         use_inscribed_circle=use_inscribed_circle,
                         number_of_full_nodes=number_of_full_nodes,
                         number_of_full_triangles=number_of_full_triangles,
                         verbose=verbose)

        # Expose Mesh attributes (FIXME: Maybe turn into methods)
        self.triangles = self.mesh.triangles        
        self.centroid_coordinates = self.mesh.centroid_coordinates
        self.vertex_coordinates = self.mesh.vertex_coordinates
        self.boundary = self.mesh.boundary
        self.neighbours = self.mesh.neighbours
        self.surrogate_neighbours = self.mesh.surrogate_neighbours
        self.neighbour_edges = self.mesh.neighbour_edges
        self.normals = self.mesh.normals
        self.edgelengths = self.mesh.edgelengths
        self.radii = self.mesh.radii
        self.areas = self.mesh.areas

        self.number_of_boundaries = self.mesh.number_of_boundaries
        self.number_of_full_nodes = self.mesh.number_of_full_nodes
        self.number_of_full_triangles = self.mesh.number_of_full_triangles
        self.number_of_triangles_per_node = \
                                    self.mesh.number_of_triangles_per_node

        self.vertex_value_indices = self.mesh.vertex_value_indices
        self.number_of_triangles = self.mesh.number_of_triangles

        self.geo_reference = self.mesh.geo_reference

        if verbose: log.critical('Initialising Domain')

        # List of quantity names entering the conservation equations
        if conserved_quantities is None:
            self.conserved_quantities = []
        else:
            self.conserved_quantities = conserved_quantities

        if evolved_quantities is None:
            self.evolved_quantities = self.conserved_quantities
        else:
            self.evolved_quantities = evolved_quantities
            
        # List of other quantity names
        if other_quantities is None:
            self.other_quantities = []
        else:
            self.other_quantities = other_quantities

        # Test that conserved_quantities are stored in the first entries of
        # evolved_quantities
        for i, quantity in enumerate(self.conserved_quantities):
            msg = 'The conserved quantities must be the first entries of '
            msg += 'evolved_quantities'
            assert quantity == self.evolved_quantities[i], msg
            

        # Build dictionary of Quantity instances keyed by quantity names
        self.quantities = {}

        for name in self.evolved_quantities:
            self.quantities[name] = Quantity(self)
        for name in self.other_quantities:
            self.quantities[name] = Quantity(self)

        # Create an empty list for explicit forcing terms
        self.forcing_terms = []

        # Setup the ghost cell communication
        if full_send_dict is None:
            self.full_send_dict = {}
        else:
            self.full_send_dict = full_send_dict

        # List of other quantity names
        if ghost_recv_dict is None:
            self.ghost_recv_dict = {}
        else:
            self.ghost_recv_dict = ghost_recv_dict

        self.processor = processor
        self.numproc = numproc

        # Setup Communication Buffers
        if verbose: log.critical('Domain: Set up communication buffers '
                                 '(parallel)')
        self.nsys = len(self.conserved_quantities)
        for key in self.full_send_dict:
            buffer_shape = self.full_send_dict[key][0].shape[0]
            self.full_send_dict[key].append(num.zeros((buffer_shape, self.nsys),
                                                      num.float))

        for key in self.ghost_recv_dict:
            buffer_shape = self.ghost_recv_dict[key][0].shape[0]
            self.ghost_recv_dict[key].append( \
                                            num.zeros((buffer_shape, self.nsys),
                                             num.float))

        # Setup cell full flag
        # =1 for full
        # =0 for ghost
        N = len(self) #number_of_elements
        self.number_of_elements = N
        self.tri_full_flag = num.ones(N, num.int)
        for i in self.ghost_recv_dict.keys():
            for id in self.ghost_recv_dict[i][0]:
                self.tri_full_flag[id] = 0

        # Test the assumption that all full triangles are store before
        # the ghost triangles.
        if not num.allclose(self.tri_full_flag[:self.number_of_full_nodes], 1):
            if self.numproc>1:
                log.critical('WARNING: Not all full triangles are store before '
                             'ghost triangles')

        # Defaults
        from anuga.config import max_smallsteps, beta_w, epsilon
        from anuga.config import CFL
        from anuga.config import timestepping_method
        from anuga.config import protect_against_isolated_degenerate_timesteps
        from anuga.config import default_order
        from anuga.config import max_timestep, min_timestep

        self.beta_w = beta_w
        self.epsilon = epsilon
        self.protect_against_isolated_degenerate_timesteps = \
                        protect_against_isolated_degenerate_timesteps


        self.centroid_transmissive_bc = False
        self.set_default_order(default_order)

        self.smallsteps = 0
        self.max_smallsteps = max_smallsteps
        self.number_of_steps = 0
        self.number_of_first_order_steps = 0
        self.CFL = CFL
        self.set_timestepping_method(timestepping_method)
        self.set_beta(beta_w)
        self.set_evolve_max_timestep(max_timestep)
        self.set_evolve_min_timestep(min_timestep)
        self.boundary_map = None  # Will be populated by set_boundary

        # Model time
        self.time = 0.0
        self.finaltime = None
        self.recorded_min_timestep = self.recorded_max_timestep = 0.0
        self.starttime = 0 # Physical starttime if any
                           # (0 is 1 Jan 1970 00:00:00)
        self.timestep = 0.0
        self.flux_timestep = 0.0

        self.last_walltime = walltime()

        # Monitoring
        self.quantities_to_be_monitored = None
        self.monitor_polygon = None
        self.monitor_time_interval = None
        self.monitor_indices = None

        # Checkpointing and storage
        from anuga.config import default_datadir

        self.datadir = default_datadir
        self.simulation_name = 'domain'
        self.checkpoint = False

        # To avoid calculating the flux across each edge twice, keep an integer
        # (boolean) array, to be used during the flux calculation.
        N = len(self) # Number_of_triangles
        self.already_computed_flux = num.zeros((N, 3), num.int)

        # Storage for maximal speeds computed for each triangle by
        # compute_fluxes.
        # This is used for diagnostics only (reset at every yieldstep)
        self.max_speed = num.zeros(N, num.float)

        if mesh_filename is not None:
            # If the mesh file passed any quantity values,
            # initialise with these values.
            if verbose: log.critical('Domain: Initialising quantity values')
            self.set_quantity_vertices_dict(vertex_quantity_dict)

        if verbose: log.critical('Domain: Done')

    ######
    # Expose underlying Mesh functionality
    ######

    def __len__(self):
        return len(self.mesh)

    def get_centroid_coordinates(self, *args, **kwargs):
        return self.mesh.get_centroid_coordinates(*args, **kwargs)

    def get_radii(self, *args, **kwargs):
        return self.mesh.get_radii(*args, **kwargs)

    def get_areas(self, *args, **kwargs):
        return self.mesh.get_areas(*args, **kwargs)

    def get_area(self, *args, **kwargs):
        return self.mesh.get_area(*args, **kwargs)

    def get_vertex_coordinates(self, *args, **kwargs):
        return self.mesh.get_vertex_coordinates(*args, **kwargs)
        
    def get_vertex_coordinate(self, *args, **kwargs):
        return self.mesh.get_vertex_coordinate(*args, **kwargs)        
        
    def get_edge_midpoint_coordinates(self, *args, **kwargs):
        return self.mesh.get_edge_midpoint_coordinates(*args, **kwargs)   
        
    def get_edge_midpoint_coordinate(self, *args, **kwargs):
        return self.mesh.get_edge_midpoint_coordinate(*args, **kwargs)        

    def get_triangles(self, *args, **kwargs):
        return self.mesh.get_triangles(*args, **kwargs)

    def get_nodes(self, *args, **kwargs):
        return self.mesh.get_nodes(*args, **kwargs)

    def get_number_of_nodes(self, *args, **kwargs):
        return self.mesh.get_number_of_nodes(*args, **kwargs)

    def get_number_of_triangles(self, *args, **kwargs):
        return self.mesh.get_number_of_triangles(*args, **kwargs)    

    def get_normal(self, *args, **kwargs):
        return self.mesh.get_normal(*args, **kwargs)

    def get_triangle_containing_point(self, *args, **kwargs):
        return self.mesh.get_triangle_containing_point(*args, **kwargs)

    def get_intersecting_segments(self, *args, **kwargs):
        return self.mesh.get_intersecting_segments(*args, **kwargs)

    def get_disconnected_triangles(self, *args, **kwargs):
        return self.mesh.get_disconnected_triangles(*args, **kwargs)

    def get_boundary_tags(self, *args, **kwargs):
        return self.mesh.get_boundary_tags(*args, **kwargs)

    def get_boundary_polygon(self, *args, **kwargs):
        return self.mesh.get_boundary_polygon(*args, **kwargs)

    # FIXME(Ole): This doesn't seem to be required
    def get_number_of_triangles_per_node(self, *args, **kwargs):
        return self.mesh.get_number_of_triangles_per_node(*args, **kwargs)

    def get_triangles_and_vertices_per_node(self, *args, **kwargs):
        return self.mesh.get_triangles_and_vertices_per_node(*args, **kwargs)

    def get_interpolation_object(self, *args, **kwargs):
        return self.mesh.get_interpolation_object(*args, **kwargs)

    def get_tagged_elements(self, *args, **kwargs):
        return self.mesh.get_tagged_elements(*args, **kwargs)

    def get_lone_vertices(self, *args, **kwargs):
        return self.mesh.get_lone_vertices(*args, **kwargs)

    def get_unique_vertices(self, *args, **kwargs):
        return self.mesh.get_unique_vertices(*args, **kwargs)

    def get_georeference(self, *args, **kwargs):
        return self.mesh.get_georeference(*args, **kwargs)

    def set_georeference(self, *args, **kwargs):
        self.mesh.set_georeference(*args, **kwargs)

    def build_tagged_elements_dictionary(self, *args, **kwargs):
        self.mesh.build_tagged_elements_dictionary(*args, **kwargs)

    def statistics(self, *args, **kwargs):
        return self.mesh.statistics(*args, **kwargs)
        
    def get_extent(self, *args, **kwargs):
        return self.mesh.get_extent(*args, **kwargs)    

    ##
    # @brief Get conserved quantities for a volume.
    # @param vol_id ID of the volume we want the conserved quantities for.
    # @param vertex If specified, use as index for edge values.
    # @param edge If specified, use as index for edge values.
    # @return Vector of conserved quantities.
    # @note If neither 'vertex' or 'edge' specified, use centroid values.
    # @note If both 'vertex' and 'edge' specified, raise exception.
    def get_conserved_quantities(self, vol_id,
                                       vertex=None,
                                       edge=None):
        """Get conserved quantities at volume vol_id.

        If vertex is specified use it as index for vertex values
        If edge is specified use it as index for edge values
        If neither are specified use centroid values
        If both are specified an exeception is raised

        Return value: Vector of length == number_of_conserved quantities
        """

        if not (vertex is None or edge is None):
            msg = 'Values for both vertex and edge was specified.'
            msg += 'Only one (or none) is allowed.'
            raise Exception, msg

        q = num.zeros(len(self.conserved_quantities), num.float)

        for i, name in enumerate(self.conserved_quantities):
            Q = self.quantities[name]
            if vertex is not None:
                q[i] = Q.vertex_values[vol_id, vertex]
            elif edge is not None:
                q[i] = Q.edge_values[vol_id, edge]
            else:
                q[i] = Q.centroid_values[vol_id]

        return q

    ##
    # @brief Get evolved quantities for a volume.
    # @param vol_id ID of the volume we want the conserved quantities for.
    # @param vertex If specified, use as index for edge values.
    # @param edge If specified, use as index for edge values.
    # @return Vector of conserved quantities.
    # @note If neither 'vertex' or 'edge' specified, use centroid values.
    # @note If both 'vertex' and 'edge' specified, raise exception.
    def get_evolved_quantities(self, vol_id,
                               vertex=None,
                               edge=None):
        """Get evolved quantities at volume vol_id.

        If vertex is specified use it as index for vertex values
        If edge is specified use it as index for edge values
        If neither are specified use centroid values
        If both are specified an exeception is raised

        Return value: Vector of length == number_of_conserved quantities
        """

        if not (vertex is None or edge is None):
            msg = 'Values for both vertex and edge was specified.'
            msg += 'Only one (or none) is allowed.'
            raise Exception, msg

        q = num.zeros(len(self.evolved_quantities), num.float)

        for i, name in enumerate(self.evolved_quantities):
            Q = self.quantities[name]
            if vertex is not None:
                q[i] = Q.vertex_values[vol_id, vertex]
            elif edge is not None:
                q[i] = Q.edge_values[vol_id, edge]
            else:
                q[i] = Q.centroid_values[vol_id]

        return q

  ##
    # @brief
    # @param flag
    def set_CFL(self, cfl=1.0):
        """Set CFL parameter, warn if greater than 1.0
        """
        if cfl > 1.0:
            self.CFL = cfl
            log.warn('Setting CFL > 1.0')

        assert cfl > 0.0
        self.CFL = cfl



    ##
    # @brief Set the relative model time.
    # @param time The new model time (seconds).
    def set_time(self, time=0.0):
        """Set the model time (seconds)."""

        # FIXME: this is setting the relative time
        # Note that get_time and set_time are now not symmetric

        self.time = time

    ##
    # @brief Get the model time.
    # @return The absolute model time (seconds).
    def get_time(self):
        """Get the absolute model time (seconds)."""

        return self.time + self.starttime

    ##
    # @brief Set the default beta for limiting.
    # @param beta The new beta value.
    def set_beta(self, beta):
        """Set default beta for limiting."""

        self.beta = beta
        for name in self.quantities:
            Q = self.quantities[name]
            Q.set_beta(beta)

    ##
    # @brief Get the beta value used for limiting.
    # @return The beta value used for limiting.
    def get_beta(self):
        """Get default beta for limiting."""

        return self.beta


    ##
    # @brief Set the behaviour of the transmissive boundary condition
    # @param flag. True or False flag
    def set_centroid_transmissive_bc(self, flag):
        """Set behaviour of the transmissive boundary condition, namely
        calculate the BC using the centroid value of neighbouring cell
        or the calculated edge value.

        Centroid value is safer.

        Some of the limiters (extrapolate_second_order_and_limit_by_edge)
        don't limit boundary edge values (so that linear functions are reconstructed),

        In this case it is possible for a run away inflow to occur at a transmissive
        boundary. In this case set centroid_transmissive_bc to True"""

        self.centroid_transmissive_bc = flag

    ##
    # @brief Get the centroid_transmissive_bc  flag
    # @return The beta value used for limiting.
    def get_centroid_transmissive_bc(self):
        """Get value of centroid_transmissive_bc flag."""

        return self.centroid_transmissive_bc


    ##
    # @brief Set the max timestep for time evolution
    # @param max_timestep The new max timestep value.
    def set_evolve_max_timestep(self, max_timestep):
        """Set default max_timestep for evolving."""

        self.evolve_max_timestep = max_timestep


    ##
    # @brief Get the max timestep for time evolution
    # @return The max timestep value.
    def get_evolve_max_timestep(self):
        """Set default max_timestep for evolving."""

        return self.evolve_max_timestep

    ##
    # @brief Set the min timestep for time evolution
    # @param min_timestep The new min timestep value.
    def set_evolve_min_timestep(self, min_timestep):
        """Set default min_timestep for evolving."""

        self.evolve_min_timestep = min_timestep


    ##
    # @brief Get the min timestep for time evolution
    # @return The min timestep value.
    def get_evolve_min_timestep(self):
        """Set default max_timestep for evolving."""

        return self.evolve_min_timestep     


  
    ##
    # @brief Set default (spatial) order.
    # @param n The new spatial order value.
    # @note If 'n' is not 1 or 2, raise exception.
    def set_default_order(self, n):
        """Set default (spatial) order to either 1 or 2."""

        msg = 'Default order must be either 1 or 2. I got %s' % n
        assert n in [1,2], msg

        self.default_order = n
        self._order_ = self.default_order

    ##
    # @brief Set values of named quantities.
    # @param quantity_dict Dictionary containing name/value pairs.
    def set_quantity_vertices_dict(self, quantity_dict):
        """Set values for named quantities.
        Supplied dictionary contains name/value pairs:

        name:  Name of quantity
        value: Compatible list, numeric array, const or function (see below)

        The values will be stored in elements following their internal ordering.
        """

        # FIXME: Could we name this a bit more intuitively
        # E.g. set_quantities_from_dictionary
        for key in quantity_dict.keys():
            self.set_quantity(key, quantity_dict[key], location='vertices')

    ##
    # @brief Set value(s) for a named quantity.
    # @param name Name of quantity to be updated.
    # @param args Positional args.
    # @param kwargs Keyword args.
    # @note If 'kwargs' dict has 'expression' key, evaluate expression.
    def set_quantity(self, name,
                           *args, **kwargs):
        """Set values for named quantity

        One keyword argument is documented here:
        expression = None, # Arbitrary expression

        expression:
          Arbitrary expression involving quantity names

        See Quantity.set_values for further documentation.
        """

        # Do the expression stuff
        if kwargs.has_key('expression'):
            expression = kwargs['expression']
            del kwargs['expression']

            Q = self.create_quantity_from_expression(expression)
            kwargs['quantity'] = Q

        # Assign values
        self.quantities[name].set_values(*args, **kwargs)

    ##
    # @brief Add to a named quantity value.
    # @param name Name of quantity to be added to.
    # @param args Positional args.
    # @param kwargs Keyword args.
    # @note If 'kwargs' dict has 'expression' key, evaluate expression.
    def add_quantity(self, name,
                           *args, **kwargs):
        """Add values to a named quantity

        E.g add_quantity('elevation', X)

        Option are the same as in set_quantity.
        """

        # Do the expression stuff
        if kwargs.has_key('expression'):
            expression = kwargs['expression']
            Q2 = self.create_quantity_from_expression(expression)
        else:
            # Create new temporary quantity
            Q2 = Quantity(self)

            # Assign specified values to temporary quantity
            Q2.set_values(*args, **kwargs)

        # Add temporary quantity to named quantity
        Q1 = self.get_quantity(name)
        self.set_quantity(name, Q1 + Q2)

    ##
    # @brief Get list of quantity names for the Domain.
    # @return List of quantity names.
    def get_quantity_names(self):
        """Get a list of all the quantity names that this domain is aware of.
        Any value in the result should be a valid input to get_quantity.
        """

        return self.quantities.keys()

    ##
    # @brief Get a quantity object.
    # @param name Name of the quantity value.
    # @param location ??
    # @param indices ??
    # @return The quantity value object.
    # @note 'location' and 'indices' are unused.
    def get_quantity(self, name,
                           location='vertices',
                           indices = None):
        """Get pointer to quantity object.

        name: Name of quantity

        See methods inside the quantity object for more options

        FIXME: clean input args
        """

        return self.quantities[name] #.get_values( location, indices = indices)

    ##
    # @brief Create a quantity value from an expression.
    # @param expression The expression (string) to be evaluated.
    # @return The expression value, evaluated from this Domain's quantities.
    # @note Valid expression operators are as defined in class Quantity.
    def create_quantity_from_expression(self, expression):
        """Create new quantity from other quantities using arbitrary expression.

        Combine existing quantities in domain using expression and return
        result as a new quantity.

        Note, the new quantity could e.g. be used in set_quantity

        Valid expressions are limited to operators defined in class Quantity

        Examples creating derived quantities:
            Depth = domain.create_quantity_from_expression('stage-elevation')
            exp = '(xmomentum*xmomentum + ymomentum*ymomentum)**0.5'
            Absolute_momentum = domain.create_quantity_from_expression(exp)
        """

        from anuga.abstract_2d_finite_volumes.util import\
             apply_expression_to_dictionary

        return apply_expression_to_dictionary(expression, self.quantities)

    ##
    # @brief Associate boundary objects with tagged boundary segments.
    # @param boundary_map A dict of boundary objects keyed by symbolic tags to
    #                     matched against tags in the internal dictionary
    #                     self.boundary.
    def set_boundary(self, boundary_map):
        """Associate boundary objects with tagged boundary segments.

        Input boundary_map is a dictionary of boundary objects keyed
        by symbolic tags to matched against tags in the internal dictionary
        self.boundary.

        As result one pointer to a boundary object is stored for each vertex
        in the list self.boundary_objects.
        More entries may point to the same boundary object

        Schematically the mapping is from two dictionaries to one list
        where the index is used as pointer to the boundary_values arrays
        within each quantity.

        self.boundary:          (vol_id, edge_id): tag
        boundary_map (input):   tag: boundary_object
        ----------------------------------------------
        self.boundary_objects:  ((vol_id, edge_id), boundary_object)

        Pre-condition:
          self.boundary has been built.

        Post-condition:
          self.boundary_objects is built

        If a tag from the domain doesn't appear in the input dictionary an
        exception is raised.
        However, if a tag is not used to the domain, no error is thrown.
        FIXME: This would lead to implementation of a default boundary condition

        Note: If a segment is listed in the boundary dictionary and if it is
        not None, it *will* become a boundary - even if there is a neighbouring
        triangle.  This would be the case for internal boundaries.

        Boundary objects that are None will be skipped.

        If a boundary_map has already been set (i.e. set_boundary has been
        called before), the old boundary map will be updated with new values.
        The new map need not define all boundary tags, and can thus change only
        those that are needed.

        FIXME: If set_boundary is called multiple times and if Boundary
        object is changed into None, the neighbour structure will not be
        restored!!!
        """

        if self.boundary_map is None:
            # This the first call to set_boundary. Store
            # map for later updates and for use with boundary_stats.
            self.boundary_map = boundary_map
        else:
            # This is a modification of an already existing map
            # Update map an proceed normally
            for key in boundary_map.keys():
                self.boundary_map[key] = boundary_map[key]

        # FIXME (Ole): Try to remove the sorting and fix test_mesh.py
        x = self.boundary.keys()
        x.sort()

        # Loop through edges that lie on the boundary and associate them with
        # callable boundary objects depending on their tags
        self.boundary_objects = []
        for k, (vol_id, edge_id) in enumerate(x):
            tag = self.boundary[(vol_id, edge_id)]

            if self.boundary_map.has_key(tag):
                B = self.boundary_map[tag]  # Get callable boundary object

                if B is not None:
                    self.boundary_objects.append(((vol_id, edge_id), B))
                    self.neighbours[vol_id, edge_id] = \
                                        -len(self.boundary_objects)
                else:
                    pass
                    #FIXME: Check and perhaps fix neighbour structure
            else:
                msg = 'ERROR (domain.py): Tag "%s" has not been ' %tag
                msg += 'bound to a boundary object.\n'
                msg += 'All boundary tags defined in domain must appear '
                msg += 'in set_boundary.\n'
                msg += 'The tags are: %s' %self.get_boundary_tags()
                raise Exception, msg

    ##
    # @brief Set quantities based on a regional tag.
    # @param args
    # @param kwargs
    def set_region(self, *args, **kwargs):
        """Set quantities based on a regional tag.

        It is most often called with the following parameters;
        (self, tag, quantity, X, location='vertices')
        tag:      the name of the regional tag used to specify the region
        quantity: Name of quantity to change
        X:        const or function - how the quantity is changed
        location: Where values are to be stored.
            Permissible options are: vertices, centroid and unique vertices

        A callable region class or a list of callable region classes
        can also be passed into this function.
        """

        if len(args) == 1:
            self._set_region(*args, **kwargs)
        else:
            # Assume it is arguments for the region.set_region function
            func = region_set_region(*args, **kwargs)
            self._set_region(func)

    ##
    # @brief ??
    # @param functions A list or tuple of ??
    def _set_region(self, functions):
        # coerce to an iterable (list or tuple)
        if type(functions) not in [types.ListType, types.TupleType]:
            functions = [functions]

        # The order of functions in the list is used.
        tagged_elements = self.get_tagged_elements()
        for function in functions:
            for tag in tagged_elements.keys():
                function(tag, tagged_elements[tag], self)

    ##
    # @brief Specify the quantities which will be monitored for extrema.
    # @param q Single or list of quantity names to monitor.
    # @param polygon If specified, monitor only triangles inside polygon.
    # @param time_interval If specified, monitor only timesteps inside interval.
    # @note If 'q' is None, do no monitoring.
    def set_quantities_to_be_monitored(self, q,
                                             polygon=None,
                                             time_interval=None):
        """Specify which quantities will be monitored for extrema.

        q must be either:
          - the name of a quantity or derived quantity such as 'stage-elevation'
          - a list of quantity names
          - None

        In the two first cases, the named quantities will be monitored at
        each internal timestep

        If q is None, monitoring will be switched off altogether.

        polygon (if specified) will only monitor triangles inside polygon.
        If omitted all triangles will be included.

        time_interval, if specified, will restrict monitoring to time steps in
        that interval. If omitted all timesteps will be included.
        """

        from anuga.abstract_2d_finite_volumes.util import\
             apply_expression_to_dictionary

        if q is None:
            self.quantities_to_be_monitored = None
            self.monitor_polygon = None
            self.monitor_time_interval = None
            self.monitor_indices = None
            return

        # coerce 'q' to a list if it's a string
        if isinstance(q, basestring):
            q = [q]

        # Check correctness and initialise
        self.quantities_to_be_monitored = {}
        for quantity_name in q:
            msg = 'Quantity %s is not a valid conserved quantity' \
                      % quantity_name

            if not quantity_name in self.quantities:
                # See if this expression is valid
                apply_expression_to_dictionary(quantity_name, self.quantities)

            # Initialise extrema information
            info_block = {'min': None,          # Min value
                          'max': None,          # Max value
                          'min_location': None, # Argmin (x, y)
                          'max_location': None, # Argmax (x, y)
                          'min_time': None,     # Argmin (t)
                          'max_time': None}     # Argmax (t)

            self.quantities_to_be_monitored[quantity_name] = info_block

        if polygon is not None:
            # Check input
            if isinstance(polygon, basestring):
                # Check if multiple quantities were accidentally
                # given as separate argument rather than a list.
                msg = ('Multiple quantities must be specified in a list. '
                       'Not as multiple arguments. '
                       'I got "%s" as a second argument') % polygon

                if polygon in self.quantities:
                    raise Exception, msg

                try:
                    apply_expression_to_dictionary(polygon, self.quantities)
                except:
                    # At least polygon wasn't expression involving quantitites
                    pass
                else:
                    raise Exception, msg

                # In any case, we don't allow polygon to be a string
                msg = ('argument "polygon" must not be a string: '
                       'I got polygon="%s"') % polygon
                raise Exception, msg

            # Get indices for centroids that are inside polygon
            points = self.get_centroid_coordinates(absolute=True)
            self.monitor_indices = inside_polygon(points, polygon)

        if time_interval is not None:
            assert len(time_interval) == 2

        self.monitor_polygon = polygon
        self.monitor_time_interval = time_interval

    ##
    # @brief Check Domain integrity.
    # @note Raises an exception if integrity breached.
    def check_integrity(self):
        self.mesh.check_integrity()

        for quantity in self.conserved_quantities:
            msg = 'Conserved quantities must be a subset of all quantities'
            assert quantity in self.quantities, msg


        for i, quantity in enumerate(self.conserved_quantities):
            msg = 'Conserved quantities must be the first entries '
            msg += 'of evolved_quantities'
            assert quantity == self.evolved_quantities[i], msg
 

    ##
    # @brief Print timestep stats to stdout.
    # @param track_speeds If True, print smallest track speed.
    def write_time(self, track_speeds=False):
        log.critical(self.timestepping_statistics(track_speeds))

    ##
    # @brief Get timestepping stats string.
    # @param track_speeds If True, report location of smallest timestep.
    # @param triangle_id If specified, use specific triangle.
    # @return A string containing timestep stats.
    def timestepping_statistics(self, track_speeds=False,
                                      triangle_id=None):
        """Return string with time stepping statistics

        Optional boolean keyword track_speeds decides whether to report
        location of smallest timestep as well as a histogram and percentile
        report.

        Optional keyword triangle_id can be used to specify a particular
        triangle rather than the one with the largest speed.
        """

        from anuga.utilities.numerical_tools import histogram, create_bins

        # qwidth determines the the width of the text field used for quantities
        qwidth = self.qwidth = 12

        msg = ''

        model_time = self.get_time()
        if self.recorded_min_timestep == self.recorded_max_timestep:
            msg += 'Time = %.4f, delta t = %.8f, steps=%d' \
                       % (model_time, self.recorded_min_timestep, \
                                    self.number_of_steps)
        elif self.recorded_min_timestep > self.recorded_max_timestep:
            msg += 'Time = %.4f, steps=%d' \
                       % (model_time, self.number_of_steps)
        else:
            msg += 'Time = %.4f, delta t in [%.8f, %.8f], steps=%d' \
                       % (model_time, self.recorded_min_timestep,
                          self.recorded_max_timestep, self.number_of_steps)

        msg += ' (%ds)' % (walltime() - self.last_walltime)
        self.last_walltime = walltime()

        if track_speeds is True:
            msg += '\n'

            # Setup 10 bins for speed histogram
            bins = create_bins(self.max_speed, 10)
            hist = histogram(self.max_speed, bins)

            msg += '------------------------------------------------\n'
            msg += '  Speeds in [%f, %f]\n' % (num.min(self.max_speed),
                                               num.max(self.max_speed))
            msg += '  Histogram:\n'

            hi = bins[0]
            for i, count in enumerate(hist):
                lo = hi
                if i+1 < len(bins):
                    # Open upper interval
                    hi = bins[i+1]
                    msg += '    [%f, %f[: %d\n' % (lo, hi, count)
                else:
                    # Closed upper interval
                    hi = num.max(self.max_speed)
                    msg += '    [%f, %f]: %d\n' % (lo, hi, count)

            N = len(self.max_speed.flat)
            if N > 10:
                msg += '  Percentiles (10%):\n'
                speed = self.max_speed.tolist()
                speed.sort()

                k = 0
                lower = min(speed)
                for i, a in enumerate(speed):
                    if i % (N/10) == 0 and i != 0:
                        # For every 10% of the sorted speeds
                        msg += '    %d speeds in [%f, %f]\n' % (i-k, lower, a)
                        lower = a
                        k = i

                msg += '    %d speeds in [%f, %f]\n'\
                           % (N-k, lower, max(speed))

            # Find index of largest computed flux speed
            if triangle_id is None:
                k = self.k = num.argmax(self.max_speed)
            else:
                errmsg = 'Triangle_id %d does not exist in mesh: %s' \
                             % (triangle_id, str(self))
                assert 0 <= triangle_id < len(self), errmsg
                k = self.k = triangle_id

            x, y = self.get_centroid_coordinates(absolute=True)[k]
            radius = self.get_radii()[k]
            area = self.get_areas()[k]
            max_speed = self.max_speed[k]

            msg += '  Triangle #%d with centroid (%.4f, %.4f), ' % (k, x, y)
            msg += 'area = %.4f and radius = %.4f ' % (area, radius)
            if triangle_id is None:
                msg += 'had the largest computed speed: %.6f m/s ' % (max_speed)
            else:
                msg += 'had computed speed: %.6f m/s ' % (max_speed)

            if max_speed > 0.0:
                msg += '(timestep=%.6f)\n' % (radius/max_speed)
            else:
                msg += '(timestep=%.6f)\n' % (0)

            # Report all quantity values at vertices, edges and centroid
            msg += '    Quantity'
            msg += '------------\n'
            for name in self.quantities:
                q = self.quantities[name]

                V = q.get_values(location='vertices', indices=[k])[0]
                E = q.get_values(location='edges', indices=[k])[0]
                C = q.get_values(location='centroids', indices=[k])

                s  = '    %s: vertex_values =  %.4f,\t %.4f,\t %.4f\n' \
                         % (name.ljust(qwidth), V[0], V[1], V[2])

                s += '    %s: edge_values =    %.4f,\t %.4f,\t %.4f\n' \
                         % (name.ljust(qwidth), E[0], E[1], E[2])

                s += '    %s: centroid_value = %.4f\n' \
                         % (name.ljust(qwidth), C[0])

                msg += s

        return msg

    ##
    # @brief Print boundary forcing stats at each timestep to stdout.
    # @param quantities A name or list of names of quantities to report.
    # @param tags A name or list of names of tags to report.
    def write_boundary_statistics(self, quantities=None, tags=None):
        log.critical(self.boundary_statistics(quantities, tags))

    # @brief Get a string containing boundary forcing stats at each timestep.
    # @param quantities A name or list of names of quantities to report.
    # @param tags A name or list of names of tags to report.
    # @note If 'quantities' is None, report all.  Same for 'tags'.
    def boundary_statistics(self, quantities=None,
                                  tags=None):
        """Output statistics about boundary forcing at each timestep

        Input:
          quantities: either None, a string or a list of strings naming the
                      quantities to be reported
          tags:       either None, a string or a list of strings naming the
                      tags to be reported

        Example output:
        Tag 'wall':
            stage in [2, 5.5]
            xmomentum in []
            ymomentum in []
        Tag 'ocean'

        If quantities are specified only report on those. Otherwise take all
        conserved quantities.
        If tags are specified only report on those, otherwise take all tags.
        """

        import types, string

        # Input checks
        if quantities is None:
            quantities = self.evolved_quantities
        elif type(quantities) == types.StringType:
            quantities = [quantities] #Turn it into a list

        msg = ('Keyword argument quantities must be either None, '
               'string or list. I got %s') % str(quantities)
        assert type(quantities) == types.ListType, msg

        if tags is None:
            tags = self.get_boundary_tags()
        elif type(tags) == types.StringType:
            tags = [tags] #Turn it into a list

        msg = ('Keyword argument tags must be either None, '
               'string or list. I got %s') % str(tags)
        assert type(tags) == types.ListType, msg

        # Determine width of longest quantity name (for cosmetic purposes)
        maxwidth = 0
        for name in quantities:
            w = len(name)
            if w > maxwidth:
                maxwidth = w

        # Output statistics
        msg = 'Boundary values at time %.4f:\n' % self.get_time()
        for tag in tags:
            msg += '    %s:\n' % tag

            for name in quantities:
                q = self.quantities[name]

                # Find range of boundary values for tag and q
                maxval = minval = None
                for i, ((vol_id,edge_id),B) in enumerate(self.boundary_objects):
                    if self.boundary[(vol_id, edge_id)] == tag:
                        v = q.boundary_values[i]
                        if minval is None or v < minval: minval = v
                        if maxval is None or v > maxval: maxval = v

                if minval is None or maxval is None:
                    msg += ('        Sorry no information available about'
                            ' tag %s and quantity %s\n') % (tag, name)
                else:
                    msg += '        %s in [%12.8f, %12.8f]\n' \
                               % (string.ljust(name, maxwidth), minval, maxval)

        return msg

    ##
    # @brief Update extrema if requested by set_quantities_to_be_monitored.
    def update_extrema(self):
        """Update extrema if requested by set_quantities_to_be_monitored.
        This data is used for reporting e.g. by running
        print domain.quantity_statistics()
        and may also stored in output files (see data_manager in shallow_water)
        """

        # Define a tolerance for extremum computations
        from anuga.config import single_precision as epsilon

        if self.quantities_to_be_monitored is None:
            return

        # Observe time interval restriction if any
        if self.monitor_time_interval is not None and\
               (self.time < self.monitor_time_interval[0] or\
               self.time > self.monitor_time_interval[1]):
            return

        # Update extrema for each specified quantity subject to
        # polygon restriction (via monitor_indices).
        for quantity_name in self.quantities_to_be_monitored:

            if quantity_name in self.quantities:
                Q = self.get_quantity(quantity_name)
            else:
                Q = self.create_quantity_from_expression(quantity_name)

            info_block = self.quantities_to_be_monitored[quantity_name]

            # Update maximum
            # (n > None is always True, but we check explicitly because
            # of the epsilon)
            maxval = Q.get_maximum_value(self.monitor_indices)
            if info_block['max'] is None or \
                   maxval > info_block['max'] + epsilon:
                info_block['max'] = maxval
                maxloc = Q.get_maximum_location()
                info_block['max_location'] = maxloc
                info_block['max_time'] = self.time

            # Update minimum
            minval = Q.get_minimum_value(self.monitor_indices)
            if info_block['min'] is None or \
                   minval < info_block['min'] - epsilon:
                info_block['min'] = minval
                minloc = Q.get_minimum_location()
                info_block['min_location'] = minloc
                info_block['min_time'] = self.time

    ##
    # @brief Return string with statistics about quantities
    # @param precision A format string to use for float values.
    # @return The stats string.
    def quantity_statistics(self, precision='%.4f'):
        """Return string with statistics about quantities for
        printing or logging

        Quantities reported are specified through method

           set_quantities_to_be_monitored
        """

        maxlen = 128 # Max length of polygon string representation

        # Output statistics
        msg = 'Monitored quantities at time %.4f:\n' % self.get_time()
        if self.monitor_polygon is not None:
            p_str = str(self.monitor_polygon)
            msg += '- Restricted by polygon: %s' % p_str[:maxlen]
            if len(p_str) >= maxlen:
                msg += '...\n'
            else:
                msg += '\n'

        if self.monitor_time_interval is not None:
            msg += '- Restricted by time interval: %s\n' \
                       % str(self.monitor_time_interval)
            time_interval_start = self.monitor_time_interval[0]
        else:
            time_interval_start = 0.0

        for quantity_name, info in self.quantities_to_be_monitored.items():
            msg += '    %s:\n' % quantity_name

            msg += '      values since time = %.2f in [%s, %s]\n' \
                       % (time_interval_start,
                          get_textual_float(info['min'], precision),
                          get_textual_float(info['max'], precision))

            msg += '      minimum attained at time = %s, location = %s\n' \
                       % (get_textual_float(info['min_time'], precision),
                          get_textual_float(info['min_location'], precision))

            msg += '      maximum attained at time = %s, location = %s\n' \
                       % (get_textual_float(info['max_time'], precision),
                          get_textual_float(info['max_location'], precision))

        return msg

    ##
    # @brief Get the timestep method.
    # @return The timestep method. One of 'euler', 'rk2' or 'rk3' or 1, 2, 3.
    def get_timestepping_method(self):
        return self.timestepping_method

    ##
    # @brief Set the tmestep method to be used.
    # @param timestepping_method One of 'euler', 'rk2' or 'rk3'.
    # @note Raises exception of method not known.
    def set_timestepping_method(self, timestepping_method):
        methods = ['euler', 'rk2', 'rk3']    
        if timestepping_method in methods:
            self.timestepping_method = timestepping_method
            return
        if timestepping_method in [1,2,3]:
            self.timetepping_method = methods[timestepping_method-1]
            return

        msg = '%s is an incorrect timestepping type' % timestepping_method
        raise Exception, msg

    ##
    # @brief Get the Domain simulation name.
    # @return The simulation name string.
    def get_name(self):
        return self.simulation_name

    ##
    # @brief Set the simulation name.
    # @param name The name of the simulation.
    # @note The simulation name is also used for the output .sww file.
    def set_name(self, name):
        """Assign a name to this simulation.
        This will be used to identify the output sww file.
        """

        # remove any '.sww' end
        if name.endswith('.sww'):
            name = name[:-4]

        self.simulation_name = name

    ##
    # @brief Get data directory path.
    # @return The data directory path string.
    def get_datadir(self):
        return self.datadir

    ##
    # @brief Set data directory path.
    # @param name The data directory path string.
    def set_datadir(self, name):
        self.datadir = name

    ##
    # @brief Get the start time value.
    # @return The start time value (float).
    def get_starttime(self):
        return self.starttime

    ##
    # @brief Set the start time value.
    # @param time The start time value.
    def set_starttime(self, time):
        self.starttime = float(time)

################################################################################
# Main components of evolve
################################################################################

    ##
    # @brief Evolve the model through time.
    # @param yieldstep Interval between yields where results are stored, etc.
    # @param finaltime Time where simulation should end.
    # @param duration Duration of simulation.
    # @param skip_initial_step If True, skip the first yield step.
    def evolve(self, yieldstep=None,
                     finaltime=None,
                     duration=None,
                     skip_initial_step=False):
        """Evolve model through time starting from self.starttime.

        yieldstep: Interval between yields where results are stored,
                   statistics written and domain inspected or
                   possibly modified. If omitted the internal predefined
                   max timestep is used.
                   Internally, smaller timesteps may be taken.

        duration: Duration of simulation

        finaltime: Time where simulation should end. This is currently
        relative time.  So it's the same as duration.

        If both duration and finaltime are given an exception is thrown.

        skip_initial_step: Boolean flag that decides whether the first
        yield step is skipped or not. This is useful for example to avoid
        duplicate steps when multiple evolve processes are dove tailed.

        Evolve is implemented as a generator and is to be called as such, e.g.

        for t in domain.evolve(yieldstep, finaltime):
            <Do something with domain and t>

        All times are given in seconds
        """

        from anuga.config import epsilon

        # FIXME: Maybe lump into a larger check prior to evolving
        msg = ('Boundary tags must be bound to boundary objects before '
               'evolving system, '
               'e.g. using the method set_boundary.\n'
               'This system has the boundary tags %s '
                   % self.get_boundary_tags())
        assert hasattr(self, 'boundary_objects'), msg

        if yieldstep is None:
            yieldstep = self.evolve_max_timestep
        else:
            yieldstep = float(yieldstep)

        self._order_ = self.default_order

        if finaltime is not None and duration is not None:
            msg = 'Only one of finaltime and duration may be specified'
            raise Exception, msg
        else:
            if finaltime is not None:
                self.finaltime = float(finaltime)
            if duration is not None:
                self.finaltime = self.starttime + float(duration)

        N = len(self)                             # Number of triangles
        self.yieldtime = self.time + yieldstep    # set next yield time

        # Initialise interval of timestep sizes (for reporting only)
        self.recorded_min_timestep = self.evolve_max_timestep
        self.recorded_max_timestep = self.evolve_min_timestep
        self.number_of_steps = 0
        self.number_of_first_order_steps = 0

        # Update ghosts
        self.update_ghosts()

        # Initial update of vertex and edge values
        self.distribute_to_vertices_and_edges()

        # Update extrema if necessary (for reporting)
        self.update_extrema()

        # Initial update boundary values
        self.update_boundary()

        # Or maybe restore from latest checkpoint
        if self.checkpoint is True:
            self.goto_latest_checkpoint()

        if skip_initial_step is False:
            yield(self.time)      # Yield initial values

        while True:
            # Evolve One Step, using appropriate timestepping method
            if self.get_timestepping_method() == 'euler':
                self.evolve_one_euler_step(yieldstep, finaltime)

            elif self.get_timestepping_method() == 'rk2':
                self.evolve_one_rk2_step(yieldstep, finaltime)

            elif self.get_timestepping_method() == 'rk3':
                self.evolve_one_rk3_step(yieldstep, finaltime)

            # Update extrema if necessary (for reporting)
            self.update_extrema()            

            self.number_of_steps += 1
            if self._order_ == 1:
                self.number_of_first_order_steps += 1

            # Yield results
            if finaltime is not None and self.time >= finaltime-epsilon:
                if self.time > finaltime:
                    # FIXME (Ole, 30 April 2006): Do we need this check?
                    # Probably not (Ole, 18 September 2008).
                    # Now changed to Exception.
                    msg = ('WARNING (domain.py): time overshot finaltime. '
                           'Contact Ole.Nielsen@ga.gov.au')
                    raise Exception, msg

                # Yield final time and stop
                self.time = finaltime
                yield(self.time)
                break

            # if we are at the next yield point
            if self.time >= self.yieldtime:
                # Yield (intermediate) time and allow inspection of domain
                if self.checkpoint is True:
                    self.store_checkpoint()
                    self.delete_old_checkpoints()

                # Pass control on to outer loop for more specific actions
                yield(self.time)

                # Reinitialise
                self.yieldtime += yieldstep                 # move to next yield
                self.recorded_min_timestep = self.evolve_max_timestep
                self.recorded_max_timestep = self.evolve_min_timestep
                self.number_of_steps = 0
                self.number_of_first_order_steps = 0
                self.max_speed = num.zeros(N, num.float)

    ##
    # @brief 'Euler' time step method.
    # @param yieldstep The reporting time step.
    # @param finaltime The simulation final time.
    def evolve_one_euler_step(self, yieldstep, finaltime):
        """One Euler Time Step
        Q^{n+1} = E(h) Q^n

        Assumes that centroid values have been extrapolated to vertices and edges
        """

        # Compute fluxes across each element edge
        self.compute_fluxes()

        # Compute forcing terms
        self.compute_forcing_terms()

        # Update timestep to fit yieldstep and finaltime
        self.update_timestep(yieldstep, finaltime)

        # Update conserved quantities
        self.update_conserved_quantities()

        # Update ghosts
        self.update_ghosts()

        # Update time
        self.time += self.timestep

        # Update vertex and edge values
        self.distribute_to_vertices_and_edges()

        # Update boundary values
        self.update_boundary()

    ##
    # @brief 'rk2' time step method.
    # @param yieldstep The reporting time step.
    # @param finaltime The simulation final time.
    def evolve_one_rk2_step(self, yieldstep, finaltime):
        """One 2nd order RK timestep
        Q^{n+1} = 0.5 Q^n + 0.5 E(h)^2 Q^n
        """

        # Save initial initial conserved quantities values
        self.backup_conserved_quantities()

        ######
        # First euler step
        ######

        # Compute fluxes across each element edge
        self.compute_fluxes()

        # Compute forcing terms
        self.compute_forcing_terms()

        # Update timestep to fit yieldstep and finaltime
        self.update_timestep(yieldstep, finaltime)

        # Update conserved quantities
        self.update_conserved_quantities()

        # Update ghosts
        self.update_ghosts()

        # Update time
        self.time += self.timestep

        # Update vertex and edge values
        self.distribute_to_vertices_and_edges()

        # Update boundary values
        self.update_boundary()

        ######
        # Second Euler step using the same timestep
        # calculated in the first step. Might lead to
        # stability problems but we have not seen any
        # example.
        ######

        # Compute fluxes across each element edge
        self.compute_fluxes()

        # Compute forcing terms
        self.compute_forcing_terms()

        # Update conserved quantities
        self.update_conserved_quantities()

        ######
        # Combine initial and final values
        # of conserved quantities and cleanup
        ######

        # Combine steps
        self.saxpy_conserved_quantities(0.5, 0.5)

        # Update ghosts
        self.update_ghosts()

        # Update vertex and edge values
        self.distribute_to_vertices_and_edges()

        # Update boundary values
        self.update_boundary()

    ##
    # @brief 'rk3' time step method.
    # @param yieldstep The reporting time step.
    # @param finaltime The simulation final time.
    def evolve_one_rk3_step(self, yieldstep, finaltime):
        """One 3rd order RK timestep
        Q^(1) = 3/4 Q^n + 1/4 E(h)^2 Q^n  (at time t^n + h/2)
        Q^{n+1} = 1/3 Q^n + 2/3 E(h) Q^(1) (at time t^{n+1})
        """

        # Save initial initial conserved quantities values
        self.backup_conserved_quantities()

        initial_time = self.time

        ######
        # First euler step
        ######

        # Compute fluxes across each element edge
        self.compute_fluxes()

        # Compute forcing terms
        self.compute_forcing_terms()

        # Update timestep to fit yieldstep and finaltime
        self.update_timestep(yieldstep, finaltime)

        # Update conserved quantities
        self.update_conserved_quantities()

        # Update ghosts
        self.update_ghosts()

        # Update time
        self.time += self.timestep

        # Update vertex and edge values
        self.distribute_to_vertices_and_edges()

        # Update boundary values
        self.update_boundary()

        ######
        # Second Euler step using the same timestep
        # calculated in the first step. Might lead to
        # stability problems but we have not seen any
        # example.
        ######

        # Compute fluxes across each element edge
        self.compute_fluxes()

        # Compute forcing terms
        self.compute_forcing_terms()

        # Update conserved quantities
        self.update_conserved_quantities()

        ######
        # Combine steps to obtain intermediate
        # solution at time t^n + 0.5 h
        ######

        # Combine steps
        self.saxpy_conserved_quantities(0.25, 0.75)

        # Update ghosts
        self.update_ghosts()

        # Set substep time
        self.time = initial_time + self.timestep*0.5

        # Update vertex and edge values
        self.distribute_to_vertices_and_edges()

        # Update boundary values
        self.update_boundary()

        ######
        # Third Euler step
        ######

        # Compute fluxes across each element edge
        self.compute_fluxes()

        # Compute forcing terms
        self.compute_forcing_terms()

        # Update conserved quantities
        self.update_conserved_quantities()

        ######
        # Combine final and initial values
        # and cleanup
        ######

        # Combine steps
        self.saxpy_conserved_quantities(2.0/3.0, 1.0/3.0)

        # Update ghosts
        self.update_ghosts()

        # Set new time
        self.time = initial_time + self.timestep

        # Update vertex and edge values
        self.distribute_to_vertices_and_edges()

        # Update boundary values
        self.update_boundary()

    ##
    # @brief Evolve simulation to a final time.
    # @param finaltime Sinulation final time.
    def evolve_to_end(self, finaltime=1.0):
        """Iterate evolve all the way to the end."""

        for _ in self.evolve(yieldstep=None, finaltime=finaltime):
            pass

    ##
    # @brief Backup conserved quantities 
    def backup_conserved_quantities(self):

        # Backup conserved_quantities centroid values
        for name in self.conserved_quantities:
            Q = self.quantities[name]
            Q.backup_centroid_values()

    ##
    # @brief Combines current C and saved centroid values S as C = aC + bS
    # @param a factor in combination
    # @param b factor in combination
    def saxpy_conserved_quantities(self, a, b):

        # Backup conserved_quantities centroid values
        for name in self.conserved_quantities:
            Q = self.quantities[name]
            Q.saxpy_centroid_values(a, b)

            


    ##
    # @brief Mapping between conserved quantites and evolved quantities
    # @param Input: q_cons array of conserved quantity values
    # @param Input: q_evol array of current evolved quantity values
    # @note  Output: Updated q_evol array
    def  conserved_values_to_evolved_values(self, q_cons, q_evol):
        """Needs to be overridden by Domain subclass
        """

        if len(q_cons) == len(q_evol):
            q_evol[:] = q_cons
        else:
            msg = 'Method conserved_values_to_evolved_values must be overridden'
            msg += ' by Domain subclass'
            raise Exception, msg

        return q_evol
    
    ##
    # @brief Update boundary values for all conserved quantities.
    def update_boundary(self):
        """Go through list of boundary objects and update boundary values
        for all conserved quantities on boundary.
        It is assumed that the ordering of conserved quantities is
        consistent between the domain and the boundary object, i.e.
        the jth element of vector q must correspond to the jth conserved
        quantity in domain.
        """

        # FIXME: Update only those that change (if that can be worked out)
        # FIXME: Boundary objects should not include ghost nodes.
        for i, ((vol_id, edge_id), B) in enumerate(self.boundary_objects):
            if B is None:
                log.critical('WARNING: Ignored boundary segment (None)')
            else:
                q_bdry = B.evaluate(vol_id, edge_id)

                if len(q_bdry) == len(self.evolved_quantities):
                    # conserved and evolved quantities are the same
                    q_evol = q_bdry
                elif len(q_bdry) == len(self.conserved_quantities):
                    # boundary just returns conserved quantities
                    # Need to calculate all the evolved quantities
                    # Use default conversion 

                    q_evol = self.get_evolved_quantities(vol_id, edge = edge_id)

                    q_evol = self.conserved_values_to_evolved_values \
                                                            (q_bdry, q_evol)
                else:
                    msg = 'Boundary must return array of either conserved'
                    msg += ' or evolved quantities'
                    raise Exception, msg
                
                for j, name in enumerate(self.evolved_quantities):
                    Q = self.quantities[name]
                    Q.boundary_values[i] = q_evol[j]

    ##
    # @brief Compute fluxes.
    # @note MUST BE OVERRIDEN IN SUBCLASS!
    def compute_fluxes(self):
        msg = 'Method compute_fluxes must be overridden by Domain subclass'
        raise Exception, msg

    ##
    # @brief
    # @param yieldstep
    # @param finaltime
    def update_timestep(self, yieldstep, finaltime):

        # Protect against degenerate timesteps arising from isolated
        # triangles
        self.apply_protection_against_isolated_degenerate_timesteps()
                
        # self.timestep is calculated from speed of characteristics
        # Apply CFL condition here
        timestep = min(self.CFL*self.flux_timestep, self.evolve_max_timestep)

        # Record maximal and minimal values of timestep for reporting
        self.recorded_max_timestep = max(timestep, self.recorded_max_timestep)
        self.recorded_min_timestep = min(timestep, self.recorded_min_timestep)

        # Protect against degenerate time steps
        if timestep < self.evolve_min_timestep:
            # Number of consecutive small steps taken b4 taking action
            self.smallsteps += 1

            if self.smallsteps > self.max_smallsteps:
                self.smallsteps = 0 # Reset

                if self._order_ == 1:
                    msg = 'WARNING: Too small timestep %.16f reached ' \
                              % timestep
                    msg += 'even after %d steps of 1 order scheme' \
                               % self.max_smallsteps
                    log.critical(msg)
                    timestep = self.evolve_min_timestep  # Try enforce min_step

                    stats = self.timestepping_statistics(track_speeds=True)
                    log.critical(stats)

                    raise Exception, msg
                else:
                    # Try to overcome situation by switching to 1 order
                    self._order_ = 1
        else:
            self.smallsteps = 0
            if self._order_ == 1 and self.default_order == 2:
                self._order_ = 2

        # Ensure that final time is not exceeded
        if finaltime is not None and self.time + timestep > finaltime :
            timestep = finaltime-self.time

        # Ensure that model time is aligned with yieldsteps
        if self.time + timestep > self.yieldtime:
            timestep = self.yieldtime - self.time

        self.timestep = timestep

    ##
    # @brief Compute forcing terms, if any.
    def compute_forcing_terms(self):
        """If there are any forcing functions driving the system
        they should be defined in Domain subclass and appended to
        the list self.forcing_terms
        """

        # The parameter self.flux_timestep should be updated
        # by the forcing_terms to ensure stability

        for f in self.forcing_terms:
            f(self)


    ##
    # @brief Update vectors of conserved quantities.
    def update_conserved_quantities(self):
        """Update vectors of conserved quantities using previously
        computed fluxes and specified forcing functions.
        """

        N = len(self) # Number_of_triangles
        d = len(self.conserved_quantities)

        timestep = self.timestep


        # Update conserved_quantities
        for name in self.conserved_quantities:
            Q = self.quantities[name]
            Q.update(timestep)

            # Note that Q.explicit_update is reset by compute_fluxes
            # Where is Q.semi_implicit_update reset?
            # It is reset in quantity_ext.c

    ##
    # @brief Sequential update of ghost cells 
    def update_ghosts(self):
        # We must send the information from the full cells and
        # receive the information for the ghost cells
        # We have a list with ghosts expecting updates

        #Update of ghost cells
        iproc = self.processor
        if self.full_send_dict.has_key(iproc):

            # now store full as local id, global id, value
            Idf  = self.full_send_dict[iproc][0]

            # now store ghost as local id, global id, value
            Idg = self.ghost_recv_dict[iproc][0]

            for i, q in enumerate(self.conserved_quantities):
                Q_cv =  self.quantities[q].centroid_values
                num.put(Q_cv, Idg, num.take(Q_cv, Idf, axis=0))

 
    ##
    # @brief Extrapolate conserved quantities from centroid to vertices
    #        and edge-midpoints for each volume.
    def distribute_to_vertices_and_edges(self):
        """Extrapolate conserved quantities from centroid to
        vertices and edge-midpoints for each volume

        Default implementation is straight first order,
        i.e. constant values throughout each element and
        no reference to non-conserved quantities.
        """

        for name in self.conserved_quantities:
            Q = self.quantities[name]
            if self._order_ == 1:
                Q.extrapolate_first_order()
            elif self._order_ == 2:
                Q.extrapolate_second_order()
            else:
                raise Exception, 'Unknown order'

    ##
    # @brief Calculate the norm of the centroid values of a specific quantity,
    #        using normfunc.
    # @param quantity
    # @param normfunc
    def centroid_norm(self, quantity, normfunc):
        """Calculate the norm of the centroid values of a specific quantity,
        using normfunc.

        normfunc should take a list to a float.

        common normfuncs are provided in the module utilities.norms
        """

        return normfunc(self.quantities[quantity].centroid_values)



    def apply_protection_against_isolated_degenerate_timesteps(self):

        # FIXME (Steve): This should be in shallow_water as it assumes x and y
        # momentum
        if self.protect_against_isolated_degenerate_timesteps is False:
            return
        
        # FIXME (Ole): Make this configurable
        if num.max(self.max_speed) < 10.0: 
            return

        # Setup 10 bins for speed histogram
        from anuga.utilities.numerical_tools import histogram, create_bins

        bins = create_bins(self.max_speed, 10)
        hist = histogram(self.max_speed, bins)

        # Look for characteristic signature
        if len(hist) > 1 and hist[-1] > 0 and \
            hist[4] == hist[5] == hist[6] == hist[7] == hist[8] == 0:
            # Danger of isolated degenerate triangles

            # Find triangles in last bin
            # FIXME - speed up using numeric package
            d = 0
            for i in range(self.number_of_full_triangles):
                if self.max_speed[i] > bins[-1]:
                    msg = 'Time=%f: Ignoring isolated high ' % self.time
                    msg += 'speed triangle '
                    msg += '#%d of %d with max speed=%f' \
                        % (i, self.number_of_full_triangles, self.max_speed[i])

                    self.get_quantity('xmomentum').\
                        set_values(0.0, indices=[i])
                    self.get_quantity('ymomentum').\
                        set_values(0.0, indices=[i])
                    self.max_speed[i]=0.0
                    d += 1


######
# Initialise module
######

# Optimisation with psyco
#from anuga.config import use_psyco

#if use_psyco:
    #try:
        #import psyco
    #except:
        #import os
        #if os.name == 'posix' and os.uname()[4] in ['x86_64', 'ia64']:
            #pass
            ## Psyco isn't supported on 64 bit systems, but it doesn't matter
        #else:
            #log.critical('WARNING: psyco (speedup) could not be imported, '
                         #'you may want to consider installing it')
    #else:
        #psyco.bind(Generic_Domain.update_boundary)
        ##psyco.bind(Domain.update_timestep) # Not worth it
        #psyco.bind(Generic_Domain.update_conserved_quantities)
        #psyco.bind(Generic_Domain.distribute_to_vertices_and_edges)


if __name__ == "__main__":
    pass