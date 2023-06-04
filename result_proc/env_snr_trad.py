import sys
from os import path
file_path = path.abspath(__file__)
root = path.dirname(path.dirname(file_path))
sys.path.append(root)

import env

ds_list = ["summeval", "newsroom", "realsumm_abs", "realsumm_ext"]
datasets = dict()
for ds_name in ds_list:
    datasets[ds_name] = eval('config.' + ds_name + '_config["human_metrics"]')

approach = "trad"
result_path_bases = [
    "/home/turx/dar-archive/results-g1-230114-053741"
]
summary_dir = "/home/turx/dar-archive/results_snr_summary_trad"
