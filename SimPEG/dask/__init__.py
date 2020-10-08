try:
    import SimPEG.dask.simulation
    import SimPEG.dask.electromagnetics.static.resistivity.simulation
    import SimPEG.dask.electromagnetics.static.induced_polarization.simulation
    # import SimPEG.dask.electromagnetics.natural_source.simulation
    import SimPEG.dask.potential_fields.base
    import SimPEG.dask.potential_fields.gravity.simulation
    import SimPEG.dask.potential_fields.magnetics.simulation
    import SimPEG.dask.data_misfit
    import SimPEG.dask.objective_function
except ImportError as err:
    print("unable to load dask operations")
    print(err)