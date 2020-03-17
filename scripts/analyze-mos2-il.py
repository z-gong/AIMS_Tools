#!/usr/bin/env python3

import sys
import argparse
import math
import configparser
import numpy as np

np.seterr(all='raise')
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt

plt.rcParams.update({'font.size': 15})

from mstools.utils import histogram, print_data_to_file
from mstools.topology import Atom, Molecule, Topology
from mstools.trajectory import Trajectory

parser = argparse.ArgumentParser()
parser.add_argument('cmd', choices=['dist', 'diffuse', 'voltage', 'charge2d', 'charge3d'],
                    help='The property to analyze')
parser.add_argument('-t', '--topology', required=True, type=str,
                    help='psf or lammps data file for topology information')
parser.add_argument('-i', '--input', nargs='+', required=True, type=str,
                    help='trajectory files for atomic positions and charges')
parser.add_argument('-c', '--config', required=True, type=str, help='Config file for analysis')
parser.add_argument('-o', '--output', required=True, type=str, help='Output prefix')
parser.add_argument('-b', '--begin', default=0, type=int, help='first frame to output')
parser.add_argument('-e', '--end', default=-1, type=int, help='last frame to output')
parser.add_argument('--topignore', nargs='+', default=[], type=str,
                    help='ignore these molecule types in topology in case topology and trajectory do not match')
parser.add_argument('--dt', default=10, type=float,
                    help='time interval (ps) between frames if not present in trajectory. '
                         'Required for diffusion analysis')
parser.add_argument('--skip', default=1, type=int, help='skip frames between output')
parser.add_argument('--voltage', default=0, type=float,
                    help='voltage drop in 3d image charge simulation. Required for charge3d analysis')
args = parser.parse_args()

eps0 = 8.854188E-12
q0 = 1.602176E-19
nm = 1E-9

top = Topology.open(args.topology)
if args.topignore != []:
    molecules = [mol for mol in top.molecules if mol.name not in args.topignore]
    top = Topology()
    top.init_from_molecules(molecules)
print('Topology info: ', top.n_atom, 'atoms;', top.n_molecule, 'molecules')

ini = configparser.ConfigParser()
if ini.read(args.config) == []:
    raise Exception('config file not exist')
mol_names = ini['molecules']['name'].split()
if set(mol_names) - set((mol.name for mol in top.molecules)) != set():
    raise Exception('Some molecules listed in config file not exist in topology')

trj = Trajectory.open(args.input)
print('Trajectory info: ', trj.n_atom, 'atoms;', trj.n_frame, 'frames')

if (top.n_atom != trj.n_atom):
    raise Exception('Number of atoms in topology and trajectory files do not match')

_frame = trj.read_frame(0)
area = _frame.box[0] * _frame.box[1]
box_z = _frame.box[2]
dz = 0.01
n_bin = math.ceil((box_z + 1.0) / dz)  # increase both the bottom and top by 0.5 nm to consider MoS2
edges = np.array([dz * i - 0.5 for i in range(n_bin + 1)])
z_array = (edges[1:] + edges[:-1]) / 2

if args.end > trj.n_frame or args.end == -1:
    args.end = trj.n_frame


def _get_atoms(mol: Molecule, names: [str]):
    return [list(filter(lambda x: x.name == name, mol.atoms))[0] for name in names]


def _get_com_position(positions, atoms: [Atom]):
    atom_masses = np.array([atom.mass for atom in atoms])
    com_mass = sum(atom_masses)
    atom_ids = [atom.id for atom in atoms]
    atom_positions = positions[atom_ids]
    com_position = np.sum(atom_positions * np.transpose(np.array([atom_masses] * 3)),
                          axis=0) / com_mass
    return com_position


def _calc_angle_xy(vec):
    '''
    Calculate the angle between a vector and xy plane
    '''
    if vec[0] == 0 and vec[1] == 0:
        theta = 90
    else:
        vec_prj = np.array([vec[0], vec[1], 0])
        cos = vec.dot(vec_prj) / np.sqrt(vec.dot(vec)) / np.sqrt(vec_prj.dot(vec_prj))
        theta = np.arccos(np.clip(cos, -1, 1)) * 180 / np.pi

    return theta


def _calc_acf(series):
    '''
    Calculate the auto correlation function of a series
    acf(t) = <h(0)h(t)>
    '''
    acf = []
    for delta in (range(int(len(series) * 0.75))):
        _tmp = []
        for t0 in range(len(series) - delta):
            v0 = series[t0]
            vt = series[t0 + delta]
            _tmp.append(v0 * vt)
        acf.append(np.mean(_tmp))

    return acf


def distribution():
    charge_array = np.array([0.] * len(z_array))
    z_atom_dict = {}
    z_com_dict = {}
    theta_dict = {}

    n_frame = 0
    for i in range(args.begin, args.end, args.skip):
        n_frame += 1
        frame = trj.read_frame(i)
        sys.stdout.write('\r    frame %i' % i)
        positions = frame.positions
        for mol in top.molecules:
            if mol.name not in mol_names:
                continue

            for atom in mol.atoms:
                z = frame.positions[atom.id][2]
                q = frame.charges[atom.id] if frame.has_charge else atom.charge
                z_idx = math.floor((z - edges[0]) / dz)
                charge_array[z_idx] += q

            section = ini['molecule.%s' % (mol.name)]
            dists = section['distributions'].split(';')
            for dist in dists:
                name, atoms = [x.strip() for x in dist.split(':')]
                if name not in z_atom_dict:
                    z_atom_dict[name] = []
                atoms = _get_atoms(mol, atoms.split())
                z_atom_dict[name] += [positions[atom.id][2] for atom in atoms]

            com_dists = section['com_distributions'].split(';')
            for dist in com_dists:
                name, atoms = [x.strip() for x in dist.split(':')]
                if name not in z_com_dict:
                    z_com_dict[name] = []
                atoms = _get_atoms(mol, atoms.split())
                com_pos = _get_com_position(positions, atoms)
                z_com_dict[name].append(com_pos[2])

            angles = section['angles'].split(';')
            for angle in angles:
                name, theta_atoms = [x.strip() for x in angle.split(':')]
                if name not in theta_dict:
                    theta_dict[name] = []
                com_atoms, z_range = [x.strip() for x in
                                      section['angle.%s.com_zrange' % name].split(':')]
                com_atoms = _get_atoms(mol, com_atoms.split())
                z_range = list(map(float, z_range.split()))
                com_pos = _get_com_position(positions, com_atoms)
                if com_pos[2] < z_range[0] or com_pos[2] > z_range[1]:
                    continue

                if len(theta_atoms.split()) == 2:
                    a1, a2 = _get_atoms(mol, theta_atoms.split())
                    vec = positions[a2.id] - positions[a1.id]
                    theta_dict[name].append(_calc_angle_xy(vec))
                elif len(theta_atoms.split()) == 3:
                    a1, a2, a3 = _get_atoms(mol, theta_atoms.split())
                    vec_12 = positions[a2.id] - positions[a1.id]
                    vec_13 = positions[a3.id] - positions[a1.id]
                    vec_normal = np.cross(vec_12, vec_13)
                    theta_dict[name].append(90 - _calc_angle_xy(vec_normal))
                else:
                    raise Exception('Invalid angle definition', name, theta_atoms)

    print('')

    name_column_dict = {'z': z_array}

    fig, ax = plt.subplots()
    ax.set(xlim=[edges[0], edges[-1]], xlabel='z (nm)', ylabel='particle density (/$nm^3$)')
    for name, z_list in z_atom_dict.items():
        x, y = histogram(z_list, bins=edges)
        ax.plot(x, y / area / dz / n_frame, label=name)
        name_column_dict['particle density - ' + name] = y / area / dz / n_frame
    ax.legend()
    fig.tight_layout()
    fig.savefig(f'{args.output}-dist.png')

    fig, ax = plt.subplots()
    ax.set(xlim=[edges[0], edges[-1]], xlabel='z (nm)', ylabel='molecule density (/$nm^3$)')
    ax2 = ax.twinx()
    ax2.set_ylabel('cumulative molecule number')
    for name, z_list in z_com_dict.items():
        x, y_com = histogram(z_list, bins=edges)
        ax.plot(x, y_com / area / dz / n_frame, label=name)
        ax2.plot(x, np.cumsum(y_com) / n_frame, '--', label=name)
        name_column_dict['molecule density - ' + name] = y_com / area / dz / n_frame
        name_column_dict['cumulative molecule number - ' + name] = np.cumsum(y_com) / n_frame
    ax.legend()
    fig.tight_layout()
    fig.savefig(f'{args.output}-dist-com.png')

    fig, ax = plt.subplots()
    ax.set(xlim=[edges[0], edges[-1]], xlabel='z (nm)', ylabel='charge density (e/$nm^3$)')
    ax.plot(z_array, charge_array / area / dz / n_frame, label=','.join(mol_names))
    name_column_dict['charge density - ' + ','.join(mol_names)] = charge_array / area / dz / n_frame
    ax.legend()
    fig.tight_layout()
    fig.savefig(f'{args.output}-charge.png')

    print_data_to_file(name_column_dict, f'{args.output}-dist.txt')

    fig, ax = plt.subplots()
    ax.set(xlim=[0, 90], ylim=[0, 0.1], xlabel='theta', ylabel='probability')
    for name, t_list in theta_dict.items():
        x, y = histogram(t_list, bins=np.linspace(0, 90, 91), normed=True)
        ax.plot(x, y, label=name)
    ax.legend()
    fig.tight_layout()
    fig.savefig(f'{args.output}-angle.png')


def diffusion():
    name_atoms_dict = {}  # {'ring': [[atom1, atom2, ...], [atom11, atom12, ...], ...]}
    t_list = []
    z_dict = {}  # {'ring': [[], [], ...]}
    residence_zrange_dict = {}
    residence_dict = {}  # {'ring': [[], [], ...]}
    acf_dict = {}  # {'ring': []}

    for mol in top.molecules:
        if mol.name not in mol_names:
            continue

        diffusions = ini['molecule.%s' % (mol.name)]['diffusions'].split(';')
        for diffusion in diffusions:
            name, atoms = [x.strip() for x in diffusion.split(':')]
            if name not in name_atoms_dict:
                name_atoms_dict[name] = []
                z_dict[name] = []
                residence_dict[name] = []
                residence_zrange_dict[name] = [float(x) for x in ini['molecule.%s' % (mol.name)][
                    'diffusion.%s.residence_zrange' % name].split()]
            name_atoms_dict[name].append(_get_atoms(mol, atoms.split()))
            z_dict[name].append([])
            residence_dict[name].append([])

    for i in range(args.begin, args.end, args.skip):
        frame = trj.read_frame(i)
        sys.stdout.write('\r    frame %i' % i)

        if frame.step != 0:
            t_list.append(frame.step / 1e6)  # ns
        else:
            t_list.append(i * args.dt / 1e3) # ns

        for name, atoms_list in name_atoms_dict.items():
            for k, atoms in enumerate(atoms_list):
                com_position = _get_com_position(frame.positions, atoms)
                z_dict[name][k].append(com_position[2])
                residence = int(com_position[2] >= residence_zrange_dict[name][0]
                                and com_position[2] <= residence_zrange_dict[name][1])
                residence_dict[name][k].append(residence)

    for name, residence_series_list in residence_dict.items():
        acf_series_list = []
        for residence_series in residence_series_list:
            acf_series_list.append(_calc_acf(residence_series))
        acf_dict[name] = np.mean(acf_series_list, axis=0) / np.mean(residence_series_list)

    print('')

    t_array = np.array(t_list) - t_list[0]
    name_cloumn_dict = {'time': t_array}
    for name, z_series_list in z_dict.items():
        fig, ax = plt.subplots(figsize=(6.4, 12.8))
        ax.set(ylim=[0, box_z], xlabel='time (ns)', ylabel='z (nm)')
        for z_series in z_series_list:
            ax.plot(t_array, z_series)
        fig.tight_layout()
        fig.savefig(f'{args.output}-diffusion-{name}.png')

    fig, ax = plt.subplots()
    ax.set(ylim=[0, 1.2], xlabel='time (ns)', ylabel='residence auto correlation')
    for name, z_series_list in z_dict.items():
        _len = len(acf_dict[name])
        ax.plot(t_array[:_len], acf_dict[name], label=name)
        name_cloumn_dict['time'] = t_array[:_len]
        name_cloumn_dict['acf - ' + name] = acf_dict[name]
    ax.plot([0, t_array[-1] * 0.5], [np.exp(-1), np.exp(-1)], '--', label='$e^{-1}$')
    ax.legend()
    fig.tight_layout()
    fig.savefig(f'{args.output}-residence.png')

    print_data_to_file(name_cloumn_dict, f'{args.output}-residence.txt')


def voltage():
    charges = np.array([0.] * n_bin)
    voltage = np.array([0.] * n_bin)

    n_frame = 0
    for i in range(args.begin, args.end, args.skip):
        n_frame += 1
        frame = trj.read_frame(i)
        sys.stdout.write('\r    frame %i' % i)

        for k, atom in enumerate(top.atoms):
            z = frame.positions[k][2]
            i_bin = math.floor((z - edges[0]) / dz)
            i_bin = min(i_bin, n_bin - 1)
            q = frame.charges[k] if frame.has_charge else atom.charge
            charges[i_bin] += q

    charges_cumulative = np.cumsum(charges) / n_frame
    charges /= area * dz * n_frame  # e/nm^3

    for i in range(1, n_bin):
        s = 0
        for j in range(0, i + 1):
            s += dz * (dz * (i - j)) * charges[j]
        voltage[i] = -s / eps0 * q0 / nm

    name_cloumn_dict = {'z': z_array}

    fig = plt.figure(figsize=[6.4, 12.8])
    ax1 = fig.add_subplot('311')
    ax1.set(xlabel='z (nm)', ylabel='charge density (e/nm$^3$)')
    ax1.plot(z_array, charges)
    ax1.plot(z_array, [0] * n_bin, '--')
    name_cloumn_dict['charge density'] = charges

    ax2 = fig.add_subplot('312')
    ax2.set(ylim=[-5, 5], xlabel='z (nm)', ylabel='cumulative charges (e)')
    ax2.plot(z_array, charges_cumulative)
    ax2.plot(z_array, [0] * n_bin, '--')
    name_cloumn_dict['cumulative charge'] = charges_cumulative

    ax3 = fig.add_subplot('313')
    ax3.set(xlabel='z (nm)', ylabel='voltage (V)')
    ax3.plot(z_array, voltage)
    ax3.plot(z_array, [0] * n_bin, '--')
    fig.tight_layout()
    fig.savefig(f'{args.output}-voltage.png')
    name_cloumn_dict['voltage'] = voltage

    print_data_to_file(name_cloumn_dict, f'{args.output}-voltage.txt')


def charge_2d():
    _conv = q0 / area / nm ** 2 * 1000  # convert from charge (e) to charge density (mC/m^2)
    # TODO need to think about how to identify cathode
    ids_cathode = [atom.id for atom in top.atoms if atom.molecule.id == 1]
    qtot_list = []
    for i in range(args.begin, args.end, args.skip):
        frame = trj.read_frame(i)
        if not frame.has_charge:
            raise Exception('charge_2d function requires charge information in trajectory')
        qtot = sum(frame.charges[ids_cathode])
        qtot_list.append(qtot)
        print('%-6i %10.6f %10.6f' % (i, qtot * _conv, qtot / len(ids_cathode) * 3))

    print('\n%-6i %10.6f %10.6f %10.6f' % (
        len(qtot_list), np.mean(qtot_list) * _conv, np.mean(qtot_list) / len(ids_cathode) * 3,
        np.mean(qtot_list) * _conv / 1000 * box_z * nm / eps0))


def charge_3d():
    _conv = q0 / area / nm ** 2 * 1000  # convert from charge (e) to charge density (mC/m^2)
    # TODO need to think about how to identify cathode
    ids_cathode = [atom.id for atom in top.atoms if atom.molecule.id == 1]
    qtot_list = []
    for i in range(args.begin, args.end, args.skip):
        frame = trj.read_frame(i)
        qtot = args.voltage * area / box_z * eps0 / q0 * nm
        for ii, atom in enumerate(top.atoms):
            if atom.molecule.name == 'MoS2' or atom.type == 'IMG':
                continue
            z = frame.positions[ii][2]
            q = frame.charges[ii] if frame.has_charge else atom.charge
            qtot += q * z / box_z
        qtot_list.append(qtot)
        print('%-6i %10.6f %10.6f' % (i, qtot * _conv, qtot / len(ids_cathode) * 3))

    print('\n%-6i %10.6f %10.6f %10.6f' % (
        len(qtot_list), np.mean(qtot_list) * _conv,
        np.mean(qtot_list) * _conv / len(ids_cathode) * 3,
        np.mean(qtot_list) * _conv / 1000 * box_z * nm / eps0))


if __name__ == '__main__':
    if args.cmd == 'dist':
        distribution()
    elif args.cmd == 'diffuse':
        diffusion()
    elif args.cmd == 'voltage':
        voltage()
    elif args.cmd == 'charge2d':
        charge_2d()
    elif args.cmd == 'charge3d':
        charge_3d()
