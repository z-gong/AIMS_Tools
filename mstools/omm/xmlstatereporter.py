import simtk.openmm as mm


class XmlStateReporter(object):
    """XMLStateReporter saves periodic checkpoints of a simulation.
    The checkpoints will overwrite one another -- only the last checkpoint
    will be saved in the file.

    To use it, create a CheckpointReporter, then add it to the Simulation's
    list of reporters. To load a checkpoint file and continue a simulation,
    use the following recipe:

    >>> simulation.loadState('state.xml-step')

    """
    def __init__(self, file, reportInterval):
        """Create a CheckpointReporter.

        Parameters
        ----------
        file : string
            The base filename to write to.
            The current step will be appended.
            Any current contents will be overwritten.
        reportInterval : int
            The interval (in time steps) at which to write checkpoints.
        """

        if not isinstance(file, str):
            raise ValueError('Invalid filename for XMLStateReporter')

        self._reportInterval = reportInterval
        self._file = file

    def describeNextReport(self, simulation):
        """Get information about the next report this object will generate.

        Parameters
        ----------
        simulation : Simulation
            The Simulation to generate a report for

        Returns
        -------
        tuple
            A six element tuple. The first element is the number of steps
            until the next report. The remaining elements specify whether
            that report will require positions, velocities, forces, energies,
            and whether wrap positions back to first cell respectively.
        """
        steps = self._reportInterval - simulation.currentStep%self._reportInterval
        return (steps, True, True, False, False, False)

    def report(self, simulation, state):
        """Generate a report.

        Parameters
        ----------
        simulation : Simulation
            The Simulation to generate a report for
        state : State
            The current state of the simulation
        """
        xml = mm.XmlSerializer.serialize(state)

        filename = '%s-%i' %(self._file, simulation.currentStep)
        with open(filename, 'w') as f:
            f.write(xml)
