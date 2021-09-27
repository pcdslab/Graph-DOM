import pandas as pd
from pandas import ExcelWriter
from pandas import ExcelFile
import numpy as np
import queue
import csv
from collections import OrderedDict
import re
import operator
import copy
import matplotlib.pyplot as plt
from tqdm import tqdm

from src import config, utils


def generate_pathways(groups):
    two_d_out = OrderedDict()
    pathway_o_dict = OrderedDict()
    precursor_pathway_hist = []
    oxygen_class_dist = []
    o_len = 20
    o_count = [0] * o_len

    for name, spec in groups:
        """
        Traverse through each group. Each group contains one spectrum (with multiple precursors)
        """
        spec.reset_index(drop=True, inplace=True)
        i = 0
        while abs(spec.loc[i, 'fragments m/z'] - name) < config.nominal_tolerance:
            """
            Get each precursor within a spectrum. A precursor is any fragment ion within 1 Da range of nominal mass.
            """
            l_precursor_mass = int(round(spec.loc[i, 'fragments m/z'] * 1000))
            precursor_string = spec.loc[i, 'Chemical formula']
            precursor_formula = utils.get_formula(precursor_string)
            
            #print('precursor: {}'.format(l_precursor_mass))
            
            l_spec = list(spec['fragments m/z'][i:])
            moz = np.round(np.asarray(l_spec) * 1000).astype(int)
            expanded_moz = np.zeros(np.amax(moz) + config.tolerance)
            expanded_moz[moz] = 1
            
            expanded_moz = np.convolve(expanded_moz, np.ones((config.tolerance,)), mode='valid')
            #print(np.sum(expanded_moz))

            for idx in range(len(expanded_moz)):
                expanded_moz[idx] = 1 if expanded_moz[idx] > 0 else 0   
        
            if expanded_moz[l_precursor_mass] != 1:
                print('precursor: {}'.format(l_precursor_mass))
                print("Invalid spectrum.")
                exit(1)
            
            pathways = queue.Queue(0)
            for loss, loss_mass in config.neutral_losses.items():
                nprecursor = l_precursor_mass
                
                for mul in range(config.multiple): #upto 5 neutral losses of one kind
                    nprecursor -= loss_mass
                    
                    if nprecursor > 0 and nprecursor <= l_precursor_mass and expanded_moz[nprecursor] == 1:
                        new_mol = OrderedDict()    
                        new_mol["CoreMass"] = nprecursor
                        #new_mol["CoreFrag"] = ""
                        if loss == "CH2" and 5 > mul+1 > 1:
                            loss = "C{}H{}".format(mul+1, 2*(mul+1))
                            new_mol["path"] = [(loss, 1)]
                        else:
                            new_mol["path"] = [(loss, mul+1)]
                        pathways.put(new_mol)
                        #print(new_mol)
                        break
                        
            core_cand = OrderedDict()
            while not pathways.empty():
                mol = pathways.get()
                is_core = True
                found = {"CH2": False, "CH4": False, "CO": False, "H2O": False, "CH3": False, "CO2": False, "C2H4": False, "O": False, "CH4O": False}
                for loss, loss_mass in config.neutral_losses.items():
                    tpmass = mol["CoreMass"]
                    for mul in range(config.multiple):
                        tpmass -= loss_mass
                        if tpmass > 0 and tpmass <= l_precursor_mass and expanded_moz[tpmass] == 1:
                            nloss_found = False
                            new_mol = copy.deepcopy(mol)
                            new_mol["CoreMass"] = tpmass
                            if loss == "CH2":
                                if 5 > mul+1 > 1:
                                    l_loss = "C{}H{}".format(mul+1, 2*(mul+1))
                                    new_mol["path"].append((l_loss, 1))
                                    nloss_found = True
                                    if l_loss == "C2H4":
                                        found["C2H4"] = True
                                if mul+1 == 1:
                                    if "CO" in new_mol["path"][-1]:
                                        del new_mol["path"][-1]
                                        new_mol["path"].append(("C2H2O", 1))
                                    if "CH4" in new_mol["path"][-1]:
                                        del new_mol["path"][-1]
                                        new_mol["path"].append(("C2H6", 1))
                                    if "H2O" in new_mol["path"][-1]:
                                        del new_mol["path"][-1]
                                        new_mol["path"].append(("CH4O", 1))
                                        found["CH4O"] = True
                                    if "O" in new_mol["path"][-1]:
                                        del new_mol["path"][-1]
                                        new_mol["path"].append(("CH2O", 1))
                                    if "CH4O" in new_mol["path"][-1]:
                                        del new_mol["path"][-1]
                                        new_mol["path"].append(("C2H6O", 1))
                                    else:
                                        new_mol["path"].append(("CH2", 1))
                                        nloss_found = True
                                        found["CH2"] = True
                            else:
                                new_mol["path"].append((loss, mul+1))
                                nloss_found = True
                                if loss in found and mul+1 == 1:
                                    found[loss] = True
                            if nloss_found:
                                is_core = False
                                pathways.put(new_mol)
                                break
                            
                for loss, loss_mass in config.alt_losses.items():
                    tpmass = mol["CoreMass"] - loss_mass
                    if tpmass > 0 and tpmass <= l_precursor_mass and expanded_moz[tpmass] == 1:
                        nloss_found = False
                        new_mol = copy.deepcopy(mol)
                        new_mol["CoreMass"] = tpmass
                        if loss == "C2H6" and not (found["CH3"] or found["CH2"] or found["CH4"]):
                            new_mol["path"].append((loss, 1))
                            nloss_found = True
                        if loss == "CH4O" and not (found["CH2"] or found["CH4"] or found["H2O"] or found["O"]):
                            new_mol["path"].append((loss, 1))
                            nloss_found = True
                        if loss == "C2H2O" and not(found["CO"] or found["CH2"]):
                            new_mol["path"].append((loss, 1))
                            nloss_found = True
                        if loss == "C2H6O" and not (found["CH4O"] or found["C2H4"] or found["H2O"]):
                            new_mol["path"].append((loss, 1))
                            nloss_found = True
                        if loss == "CH2O" and not (found["CH2"] or found["O"]):
                            new_mol["path"].append((loss, 1))
                            nloss_found = True
                        if nloss_found:
                            is_core = False
                            pathways.put(new_mol)
                            
                if is_core and expanded_moz[mol["CoreMass"]] == 1 and utils.is_path_valid(mol["path"], precursor_formula):
                    new_mol = copy.deepcopy(mol)
                    #print(new_mol)
                    key = ""
                    for loss, mul in new_mol["path"]:
                        key += f"{mul}{loss} "
                    key = key.strip(" ")

                    if key not in core_cand:
                        if not utils.is_path_valid(new_mol["path"], precursor_formula):
                            print(print("{} is not valid for precursor {}".format(new_mol["path"], utils.get_string_from_formula(precursor_formula))))
                        core_cand[key] = new_mol

            #while not pathways.empty():
            #    print(pathways.get())
            print(spec.loc[i, 'Chemical formula'] + ' Number of possible combinations: ' + str(len(core_cand)))
            
            """Generate the histogram of number of pathways per precursor m/z"""
            precursor_pathway_hist.append([spec.loc[i, 'Precursor m/z'], len(core_cand)])
            
            """Get the oxygen group distribution."""
            tmp_o_count = utils.get_formula(spec.loc[i, 'Chemical formula'])['O']
            if 0 <= tmp_o_count <= o_len:
                o_count[tmp_o_count] += len(core_cand)
            
            # Go through each pathways, get core-fragment, and fill the dictionary
            core_dict = OrderedDict()
            
            for key, nl_row in core_cand.items():
                core_str = utils.get_core_string_2(nl_row["path"], precursor_formula)
                
                nl_row["path"] = utils.get_fragment_seq_from_nloss(nl_row["path"], precursor_formula)
                
                if core_str in core_dict:
                    core_dict[core_str][key] = nl_row
                else:
                    tmp_dict = OrderedDict()
                    tmp_dict[key] = nl_row
                    core_dict[core_str] = tmp_dict
            
            pathway_o_dict[precursor_string] = core_dict
            #print(precursor_string)
            #print(core_dict)
            
            i += 1

    return pathway_o_dict, precursor_pathway_hist, o_count