import itertools
import numpy as np
from .system import System
from ..forcefield.ffterm import *
from ..forcefield import ForceField
from ..topology import Pdb, Psf
from ..trajectory import Frame, Trajectory, Gro
from .. import logger


class CharmmExporter():
    def __init__(self):
        pass

    @staticmethod
    def export(system: System, pdb_out, psf_out, prm_out):
        if pdb_out is not None:
            CharmmExporter.export_pdb(system, pdb_out)
        if psf_out is not None:
            CharmmExporter.export_psf(system, psf_out)
        if prm_out is not None:
            CharmmExporter.export_prm(system, prm_out)

    @staticmethod
    def export_pdb(self, pdb_out='conf.pdb'):
        Pdb.save_to(self._topology, pdb_out)

    @staticmethod
    def export_psf(self, psf_out='topol.psf'):
        Psf.save_to(self._topology, psf_out)

    @staticmethod
    def export_prm(system, prm_out='ff.prm'):
        supported_terms = {LJ126Term,
                           HarmonicBondTerm,
                           HarmonicAngleTerm,
                           PeriodicDihedralTerm,
                           OplsImproperTerm, HarmonicImproperTerm,
                           DrudeTerm}
        unsupported = system.ff_classes - supported_terms
        if unsupported != set():
            raise Exception('Unsupported FF terms: %s'
                            % (', '.join(map(lambda x: x.__name__, unsupported))))

        if OplsImproperTerm in system.ff_classes:
            logger.warning('CHARMM only supports harmonic form for impropers. '
                           'OPLS impropers will be exported as harmonic')

        string = '* Created by mstools\n'
        string += '*\n'

        string += '\nATOMS\n'
        for i, atype in enumerate(system._ff.atom_types.values()):
            # set mass to 0 in case not defined in FF
            string += '  MASS %6i %10s %10.4f\n' % (i + 1, atype.name, max(atype.mass, 0))

        unique_bonds: {(str): BondTerm} = {}
        for bond in system._topology.bonds:
            name = (bond.atom1.type, bond.atom2.type)
            if name not in unique_bonds and tuple(reversed(name)) not in unique_bonds:
                if bond.is_drude:
                    parent = bond.atom2 if bond.atom1.is_drude else bond.atom1
                    pterm = system._polarizable_terms[parent]
                    bterm = HarmonicBondTerm(name[0], name[1], 0.0, pterm.k)
                else:
                    bterm = system._bond_terms[id(bond)]
                unique_bonds[name] = bterm

        unique_angles = {}
        for angle in system._topology.angles:
            name = (angle.atom1.type, angle.atom2.type, angle.atom3.type)
            if name not in unique_angles and tuple(reversed(name)) not in unique_angles:
                unique_angles[name] = system._angle_terms[id(angle)]
        unique_dihedrals = {}
        for dihedral in system._topology.dihedrals:
            name = (dihedral.atom1.type, dihedral.atom2.type,
                    dihedral.atom3.type, dihedral.atom4.type)
            if name not in unique_dihedrals and tuple(reversed(name)) not in unique_dihedrals:
                unique_dihedrals[name] = system._dihedral_terms[id(dihedral)]
        unique_impropers = {}
        for improper in system._topology.impropers:
            name = (improper.atom1.type, improper.atom2.type,
                    improper.atom3.type, improper.atom4.type)
            if name not in unique_impropers and tuple(reversed(name)) not in unique_impropers:
                unique_impropers[name] = system._improper_terms[id(improper)]

        string += '\nBONDS\n'
        string += '''!V(bond) = Kb(b - b0)**2
!Kb: kcal/mole/A**2
!b0: A
!
!      atom type Kb          b0
'''
        for (at1, at2), bterm in unique_bonds.items():
            string += '%10s %10s %16.6f %10.4f\n' % (
                at1, at2, bterm.k / 4.184 / 100, bterm.length * 10)

        string += '\nANGLES\n'
        string += '''!V(angle) = Ktheta(Theta - Theta0)**2
!V(Urey-Bradley) = Kub(S - S0)**2
!Ktheta: kcal/mole/rad**2
!Theta0: degrees
!Kub: kcal/mole/A**2 (Urey-Bradley)
!S0: A
!
!      atom types     Ktheta    Theta0   Kub     S0
'''
        for (at1, at2, at3), aterm in unique_angles.items():
            string += '%10s %10s %10s %12.6f %12.4f\n' % (
                at1, at2, at3, aterm.k / 4.184, aterm.theta)

        string += '\nDIHEDRALS\n'
        string += '''!V(dihedral) = Kchi(1 + cos(n(chi) - delta))
!Kchi: kcal/mole
!n: multiplicity
!delta: degrees
!
!atom types             Kchi    n   delta
'''
        for (at1, at2, at3, at4), dterm in unique_dihedrals.items():
            for para in dterm.parameters:
                string += '%10s %10s %10s %10s %12.6f %4i %8.2f\n' % (
                    at1, at2, at3, at4, para.k / 4.184, para.n, para.phi)
            if len(dterm.parameters) == 0:
                string += '%10s %10s %10s %10s %12.6f %4i %8.2f  ; no dihedral parameters\n' % (
                    at1, at2, at3, at4, 0.0, 1, 0.0)

        string += '\nIMPROPERS\n'
        string += '''!V(improper) = Kpsi(psi - psi0)**2
!Kpsi: kcal/mole/rad**2
!psi0: degrees
!
!      atom types           Kpsi      ignored         psi0
'''
        for (at1, at2, at3, at4), iterm in unique_impropers.items():
            if type(iterm) == HarmonicImproperTerm:
                phi = iterm.phi
            elif type(iterm) == OplsImproperTerm:
                phi = 0.0
            else:
                raise Exception('Only HarmonicImproperTerm and OplsImproperTerm are supported')
            string += '%10s %10s %10s %10s %12.6f %4i %8.2f\n' % (
                at1, at2, at3, at4, iterm.k / 4.184, 0, phi)

        string += '\nNONBONDED\n'
        string += '''!V(Lennard-Jones) = Eps,i,j[(Rmin,i,j/ri,j)**12 - 2(Rmin,i,j/ri,j)**6]
!epsilon: kcal/mole, Eps,i,j = sqrt(eps,i * eps,j)
!Rmin/2: A, Rmin,i,j = Rmin/2,i + Rmin/2,j
!
!      atom  ignored    epsilon      Rmin/2   ignored   eps,1-4       Rmin/2,1-4
'''
        for atype in system._ff.atom_types.values():
            vdw = system._ff.get_vdw_term(atype, atype)
            rmin = vdw.sigma * 2 ** (1 / 6)
            eps14 = vdw.epsilon * system._ff.scale_14_vdw
            string += '%10s %10.4f %12.6f %12.6f %10.4f %12.6f %12.6f  ! %s\n' % (
                atype.name, 0.0, -vdw.epsilon / 4.184, rmin / 2 * 10,
                0.0, -eps14 / 4.184, rmin / 2 * 10, ' '.join(vdw.comments))

        if len(system._ff.pairwise_vdw_terms) != 0:
            string += '\nNBFIX\n'
            string += '!      atom  atom  epsilon      Rmin   eps,1-4       Rmin,1-4\n'
            for atype1, atype2 in itertools.combinations(system._ff.atom_types.values(), 2):
                vdw = system._ff.get_vdw_term(atype1, atype2, mixing=False)
                if vdw is None:
                    continue
                rmin = vdw.sigma * 2 ** (1 / 6)
                eps14 = vdw.epsilon * system._ff.scale_14_vdw
                string += '%10s %10s %12.6f %12.6f %12.6f %12.6f  ! %s\n' % (
                    atype1.name, atype2.name, -vdw.epsilon / 4.184, rmin * 10,
                    -eps14 / 4.184, rmin * 10, ' '.join(vdw.comments))

        string += '\nEND\n'

        with open(prm_out, 'w') as f:
            f.write(string)
