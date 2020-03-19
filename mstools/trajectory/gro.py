import numpy as np
from ..topology import Topology
from . import Trajectory, Frame


class Gro(Trajectory):
    '''
    Read and write box, atomic positions and optionally velocities from/to gro file
    Since gro is using fixed width format, the residue id and atom id are ignored
    When writing to gro file, the residue name will get truncated with max length of 4
    '''

    def __init__(self, trj_file, mode='r'):
        super().__init__()
        self._file = open(trj_file, mode)
        if mode == 'r':
            self._get_info()
        elif mode == 'w':
            pass

    def _get_info(self):
        '''
        Read the number of atoms and record the offset of lines and frames,
        so that we can read arbitrary frame later
        '''
        try:
            self._file.readline()
            self.n_atom = int(self._file.readline())
        except:
            print('Invalid gro file')
            raise
        self._file.seek(0)

        # read in the file once and build a list of line offsets
        self._line_offset = []
        offset = 0
        for line in self._file:
            self._line_offset.append(offset)
            offset += len(line)
        # the last element is the length of whole file
        self._line_offset.append(offset)
        self._file.seek(0)

        # build a list of frame offsets
        self.n_frame = len(self._line_offset) // (3 + self.n_atom)
        self._frame_offset = []
        for i in range(self.n_frame + 1):
            line_start = (3 + self.n_atom) * i
            self._frame_offset.append(self._line_offset[line_start])

        self._frame = Frame(self.n_atom)

    def read_frame(self, i_frame):
        # skip to frame i and read only this frame
        self._file.seek(self._frame_offset[i_frame])
        string = self._file.read(self._frame_offset[i_frame + 1] - self._frame_offset[i_frame])
        self._read_frame_from_string(string, self._frame)

        return self._frame

    def read_frames(self, i_frames: [int]) -> [Frame]:
        frames = []
        for i in i_frames:
            frame = Frame(self.n_atom)
            # skip to frame i and read only this frame
            self._file.seek(self._frame_offset[i])
            string = self._file.read(self._frame_offset[i + 1] - self._frame_offset[i])
            self._read_frame_from_string(string, frame)
            frames.append(frame)

        return frames

    def _read_frame_from_string(self, string: str, frame: Frame):
        lines = string.splitlines()
        # assume there are velocities. we'll see later
        frame.has_velocity = True
        for i in range(self.n_atom):
            line = lines[i + 2]
            x = float(line[20:28])
            y = float(line[28:36])
            z = float(line[36:44])
            frame.positions[i] = np.array([x, y, z])

            if frame.has_velocity:
                try:
                    vx = float(line[44:52])
                    vy = float(line[52:60])
                    vz = float(line[60:68])
                except:
                    frame.has_velocity = False
                else:
                    frame.velocities[i] = np.array([vx, vy, vz])
        _box = tuple(map(float, lines[self.n_atom + 2].split()))
        if len(_box) == 3:
            frame.cell.set_box(_box)
        elif len(_box) == 9:
            ax, by, cz, ay, az, bx, bz, cx, cy = _box
            frame.cell.set_box([[ax, ay, az], [bx, by, bz], [cx, cy, cz]])
        else:
            raise ValueError('Invalid box')

        return frame

    def write_frame(self, topology: Topology, frame: Frame, subset=None, write_velocity=False):
        if write_velocity and not frame.has_velocity:
            raise Exception('Velocities are requested but not exist in frame')

        self._file.write('created by mstools. step %i\n' % frame.step)
        if subset is None:
            subset = list(range(topology.n_atom))
        self._file.write('%i\n' % len(subset))

        for id in subset:
            atom = topology.atoms[id]
            mol = atom.molecule
            pos = frame.positions[id]
            line = '%5i%5s%5s%5i%8.3f%8.3f%8.3f' % (
                (mol.id + 1) % 100000, mol.name[:4], atom.symbol, (atom.id + 1) % 100000,
                pos[0], pos[1], pos[2])
            if write_velocity:
                vel = frame.velocities[id]
                line += '%8.3f%8.3f%8.3f' % (vel[0], vel[1], vel[2])
            self._file.write(line + '\n')

        a, b, c = frame.cell.vectors
        self._file.write(' %.4f %.4f %.4f %.4f %.4f %.4f %.4f %.4f %.4f' %
                         (a[0], b[1], c[2], a[1], a[2], b[0], b[2], c[0], c[1]))

        self._file.flush()
