#!/home/jmframe/programs/anaconda3/bin/python3

import numpy as np
import pandas as pd
import random
from math import sin, cos, sqrt, atan2, radians
from ease_grid import EASE2_grid
import matplotlib
matplotlib.use('Agg') # Must be before importing matplotlib.pyplot or pylab!
import matplotlib.pyplot as plt
from matplotlib import cm

# approximate radius of earth in km
def distance(lat1,lat2,lon1,lon2):
    R = 6373.0

    lat1 = radians(lat1)
    lon1 = radians(lon1)
    lat2 = radians(lat2)
    lon2 = radians(lon2)
    
    dlon = lon2 - lon1
    dlat = lat2 - lat1

    a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    distance = R * c

    return(distance) #km

class IMPAaCS:

    """
    Update: June 3rd 2021 @ 11:30AM Central Time, Setting limits for SiO2 percent bins from 1-100, so we can get min/max
    Update: May 29th 2021 @ 2:30PM Central Time, Search only the subset of grids for impact, else skip
    Update: May 28th 2021 @ 12:19PM Central Time, with Jordan to get ensembles running
    
    Dynamic geospatial model of IMPaCS, 
    using the size-frequency distribution of impacts scaled from the lunar surface, 
    we generate the volume and abundance of this enriched crust on Earth’s surface 
    during the Hadean to determine how rapidly it evolved.
    """
    
    impact_test_id = str(round(0.14122179,4))+' '+str(round(0.18672199,4))
    
    def __init__(self, egrid, 
                 verbose=False,
                 max_depth_of_impact_melt=330,
                 ensemble = 0,
                 primitive_initial_state=45,
                 fraction_upper_layer = 2/3,
                 target_SiO2 = 62.58,     # From sudbury
                 upper_SiO2 = 68.71,      # From sudbury
                 n_layers_impact_melt = 2,
                 z_discretized_km = int(2),
                 proportion_melt_from_impact = 1/3,
                 sim_time=0,
                 lon_lims = [-180, 180], lat_lims = [-45, 45]):
        self.egrid = egrid
        self.verbose=verbose
        self.ensemble=ensemble
        self.primitive_initial_state = primitive_initial_state
        self.max_depth_of_impact_melt = max_depth_of_impact_melt
        self.fraction_upper_layer = fraction_upper_layer        # d_upper / Mi (from Sudbury)
        self.fraction_lower_layer = 1-self.fraction_upper_layer # d_lower / Mi (from Sudbury)
        self.n_layers_impact_melt = n_layers_impact_melt
        self.target_SiO2 = target_SiO2 # From sudbury
        self.upper_SiO2 = upper_SiO2  # From sudbury
        self.z_discretized_km = z_discretized_km
        self.proportion_melt_from_impact = proportion_melt_from_impact
        self.average_target = self.primitive_initial_state
        self.average_target_list = [self.primitive_initial_state]
        self.top_layer_at_test_cell = [self.primitive_initial_state]
        self.average_test_target_list = [self.primitive_initial_state]
        self.n_x = self.egrid.londim.shape[0]
        self.n_y = self.egrid.latdim.shape[0]
        self.sim_time=sim_time
        
        self.count_test_hits = 0
        self.grid_cell_state = {}
        self.impacted_grid_cells = []
        self.impactors_at_test_cell = [0]
        self.test_time = [0]
                
        self.sample_percents = {}
        self.lon_lims=lon_lims
        self.lat_lims=lat_lims
        self.lon_subset=[]
        self.lat_subset=[]
        
        # Set up the grids so we don't search the whole planet for every impact
        self.get_subset_of_grids()
        self.n_x = len(self.lon_subset)
        self.n_y = len(self.lat_subset)
        
        # Finally we set up the state data
        self.state_prep()
        
    #--------------------------------------------------------------------------------------------------
    def update(self, impact_loc, impactor_diameter, sim_time=0):
        self.sim_time = sim_time
        self.impact_dimensions(impactor_diameter)
        self.find_the_grid(impact_loc)
        if len(self.impacted_grid_cells) > 0:
            self.get_average_target(impactor_diameter)
            self.loop_impact_grid(impactor_diameter)
        
    #--------------------------------------------------------------------------------------------------
    #---- THIS IS THE MAIN CODE -------------------- THIS IS THE MAIN CODE ----------------------------
    #--------------------------------------------------------------------------------------------------
    def state_dynamics(self, impactor_diameter, grid_cell_id):
        """
        This is the critical component of this model
        This function will change the chemical makeup of each grid cell
            according to the chemical theory put forward by Faltys-Wielicki [2021]
        """
        
        #####      DYNAMIC FACTORS       ############################
        depth_of_impact_melt = impactor_diameter * self.proportion_melt_from_impact # D/3

        #Vertical discretization.
        melt_layers = int(depth_of_impact_melt / self.z_discretized_km)

        lower_layer  = range(int(round(self.fraction_upper_layer * melt_layers,2)), melt_layers)
        upper_layer  = range(0, int(round(self.fraction_upper_layer * melt_layers,2)))

        fracionated_melt = depth_of_impact_melt * self.fraction_upper_layer #Units: km

        fractionation_factor = 1 - (self.target_SiO2 / self.upper_SiO2)

        #####      DO THE DYANMICS       #############################
        # Set lower layer to primitive initial state.  
        for i in lower_layer:
            self.grid_cell_state[grid_cell_id][i] = self.primitive_initial_state

        # Impact melt portion  (Upper)
        for i in upper_layer:
            self.grid_cell_state[grid_cell_id][i] = self.average_target / (1 - fractionation_factor)

        # Weighted average of upper    
        wt_sio2_upper = self.grid_cell_state[grid_cell_id][0]

        # Lower of impact melt portion
        for i in lower_layer:
            numerator = self.average_target-(self.fraction_upper_layer * wt_sio2_upper)
            self.grid_cell_state[grid_cell_id][i] = numerator / self.fraction_lower_layer

        for i in range(melt_layers):
            self.grid_cell_state[grid_cell_id][i] = np.round(self.grid_cell_state[grid_cell_id][i],1)
    
    #--------------------------------------------------------------------------------------------------    
    def state_prep(self):
        total_layers = int(self.max_depth_of_impact_melt / self.z_discretized_km)
        for ilon in self.lon_subset:
            for ilat in self.lat_subset:
                grid_cell_id = str(round(ilon,4))+' '+str(round(ilat,4))
                self.grid_cell_state[grid_cell_id] = np.ones(total_layers) * self.primitive_initial_state
        
    #--------------------------------------------------------------------------------------------------    
    def get_average_target(self, impactor_diameter):
        average_target = 0
        for grid_cell in self.impacted_grid_cells:
            grid_cell_id = str(round(grid_cell[0],4))+' '+str(round(grid_cell[1],4))
            ### If the grid cell has not been hit yet, it is the initial primitive value
            if grid_cell_id in self.grid_cell_state.keys():
                average_target += np.sum(self.grid_cell_state[grid_cell_id][:self.z_layers])
            else:
                average_target += self.primitive_initial_state * self.z_layers
        self.average_target = average_target/(len(self.impacted_grid_cells) * self.z_layers)
        
    #--------------------------------------------------------------------------------------------------    
    def find_the_grid(self, impact_loc):
        self.impacted_grid_cells = [] # first reset the impacted grid cells, then fill them up
        Dmin=10000000
        for ilon in self.lon_subset:
            for ilat in self.lat_subset:
                D = distance(impact_loc[0],ilat,impact_loc[1],ilon)
                if D < Dmin:
                    Dmin = D
                if D <= self.crator_radius:
                    self.impacted_grid_cells.append([ilon, ilat])
        if len(self.impacted_grid_cells) < 1:
            
            # If the crator didn't impact any grids in the subsample, 
            # Check to see if the min distance is smaller than the length of a grid.
            # If it is, we can assign it to the closest grid.
            # If not, then just ignore it.
            if Dmin < 30:
                if self.verbose:
                    print("Warning. There are no grids impacted!")
                    print('Dmin', Dmin, 'crator radius', self.crator_radius, 'impact location', impact_loc)
                for ilon in self.lon_subset:
                    for ilat in self.lat_subset:
                        D = distance(impact_loc[0],ilat,impact_loc[1],ilon)
                        if D == Dmin:
                            self.impacted_grid_cells.append([ilon, ilat])
                            if self.verbose:
                                print('impacting grid cell', [ilon, ilat])

    #--------------------------------------------------------------------------------------------------    
    def loop_impact_grid(self, impactor_diameter):
        for grid_cell in self.impacted_grid_cells:
            grid_cell_id = str(round(grid_cell[0],4))+' '+str(round(grid_cell[1],4))

            ################      DO THE DYANMICS       #############################
            self.state_dynamics(impactor_diameter, grid_cell_id)

            self.test_one_grid_cell(grid_cell_id, impactor_diameter)
    #--------------------------------------------------------------------------------------------------    
    def impact_dimensions(self, impactor_diameter):
            # The impact crator is 10*Diameter, so the radius is half that
            self.crator_diameter = 10*impactor_diameter
            self.crator_radius = self.crator_diameter/2
            self.z_layers = int(np.ceil(impactor_diameter / self.z_discretized_km))

    #--------------------------------------------------------------------------------------------------    
    def test_one_grid_cell(self, grid_cell_id, impactor_diameter):
        ##### Testing one cell:
        if grid_cell_id == self.impact_test_id:
            self.count_test_hits+=1
            self.test_time.append(self.sim_time)
            self.impactors_at_test_cell.append(impactor_diameter)
            self.average_test_target_list.append(self.average_target)
            self.top_layer_at_test_cell.append(self.grid_cell_state[self.impact_test_id][0])

    #--------------------------------------------------------------------------------------------------
    def re_bin_sio2(self, temp_state, s_min=1, s_max=100, ds=1):
        """
            Functionto place the mean SiO2 into the proper bin for distribution.
        """
        for s in range(s_min,s_max,ds):
            if temp_state<=s:
                return s
            elif temp_state>=s_max:
                return s_max
            else:
                continue

    # ---------------------------------------------------------------------------------------------
    def plot_map_and_bar(self, save_figure=False, plot_figure=False, fig_path='./'):
        
        """
            Function for plotting 2D map of SiO2 States.
            Function inputs:
                save_figure=False
                plot_figure=False
                fig_path='./'
        """
        
        if not plot_figure and not save_figure:
            print('not plotting figure')
            return

        z = np.zeros([self.n_x, self.n_y])
        bar_list = []
        for i, ilon in enumerate(self.lon_subset):
            for j, ilat in enumerate(self.lat_subset):
                grid_cell = str(round(ilon,4))+' '+str(round(ilat,4))
                temp_state = np.mean(self.grid_cell_state[grid_cell][0:2])
                temp_state = self.re_bin_sio2(temp_state)
                z[i, j] = temp_state
        
        X, Y = np.meshgrid(self.lon_subset, self.lat_subset)
        
        fig = plt.figure(figsize=(12, 7))

        grid = plt.GridSpec(1, 7, wspace = .1, hspace = .1)
        plt.subplots_adjust(wspace= 0.1, hspace= 0.1)

        plt.subplot(grid[0, :5])
        
        levels = np.arange(34, 70, 2)
        cmap = cm.jet
        cs = plt.contourf(X, Y, np.transpose(z), levels, cmap=cm.get_cmap(cmap, len(levels) - 1)) 
        cbar = fig.colorbar(cs, ticks=range(34,70,2))

        plt.title('Surface SiO2 content at {}myr'.format(int(self.sim_time/1000000)))
        plt.xlabel('longitude')
        plt.ylabel('latitude')
        plt.xlim(self.lon_lims)
        plt.ylim(self.lat_lims)
        plt.xticks(np.arange(self.lon_lims[0], self.lat_lims[1], 10))
        
        plt.subplot(grid[0, 5:])
        plt.bar(list(self.sample_percents.keys()), list(self.sample_percents.values()), width=1.2)
        plt.xlim([35,70])
        plt.ylim([0,40])
        plt.xlabel('Surface SiO2 content')
        plt.ylabel('Percent surface area')
        plt.xticks(np.arange(35, 75, 5))
        if save_figure:
            plt.savefig(fig_path+'{}myr.png'.format(int(self.sim_time/1000000)), 
                    bbox_inches='tight', dpi = 100)
        if plot_figure:
            plt.show()
        plt.close()
        
    # ---------------------------------------------------------------------------------------------
    def do_sample_percents(self, n_layers=2):
        
        """
            Function Summarizing and saving SiO2 percentages in a sample region.
            Function inputs:
                plot_x_lims = Limits of longitude for SiO2 sample
                plot_y_lims = Limits of latitude for SiO2 sample
                n_layers = number of discretized layers to include in the average.
        """
        
        z = np.zeros([self.n_x, self.n_y])
        bar_list = []
        for i, ilon in enumerate(self.lon_subset):
            for j, ilat in enumerate(self.lat_subset):
                grid_cell = str(round(ilon,4))+' '+str(round(ilat,4))
                temp_state = np.mean(self.grid_cell_state[grid_cell][0:2])
                temp_state = self.re_bin_sio2(temp_state)
                z[i, j] = temp_state
                
                mean_sio2 = np.mean(self.grid_cell_state[grid_cell][0:2])
                if not np.isnan(mean_sio2):
                    bar_list.append(self.re_bin_sio2(mean_sio2))
        
        bar_list = [x for x in bar_list if x != None]
        
        bar_data = {}
        for u in np.unique(bar_list):
            bar_data[u] = 100*bar_list.count(u)/len(bar_list)

        self.sample_percents = bar_data
        
    # ---------------------------------------------------------------------------------------------
    def get_subset_of_grids(self):
        for ilon in self.egrid.londim:
            for ilat in self.egrid.latdim:
                if ilat > self.lat_lims[0] and ilat < self.lat_lims[1]:
                    if ilon > self.lon_lims[0] and ilon < self.lon_lims[1]:
                        if ilat not in self.lat_subset:
                            self.lat_subset.append(ilat)
                        if ilon not in self.lon_subset:
                            self.lon_subset.append(ilon)


