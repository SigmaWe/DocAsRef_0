import json
import pickle

import numpy as np

import dataloader.newsroom as newsroom
import dataloader.realsumm as realsumm

import scipy

model_scores = dict()
corr = dict()
approaches = ['trad', 'new']


def read_system_scores() -> dict:
    with open('results/model/scores.json', 'r') as infile:
        return json.load(infile)


def newsroom_read(metrics: list) -> dict:
    """
    Return data structure:
    {
        docID: {
            system1: {
                "Coherence":       float,
                "Fluency":         float,
                "Informativeness": float,
                "Relevance":       float,
                "precision":       float,
                "recall":          float,
                "f1":              float
            }
            system2: { ... }
            ...
            system7: {... }
        }
    }
    """
    system_scores = dict()
    for approach in approaches:
        system_scores[approach] = dict()
    _, _, _, human_scores = newsroom.read('dataloader')
    for i in range(len(human_scores)):
        for approach in approaches:
            system_scores[approach][i] = dict()
            human_keys = human_scores[i].keys()
            for metric in metrics:
                if metric != 'bleu':
                    system_scores[approach][i][metric] = dict()
                    for key in human_keys:
                        system_scores[approach][i][metric][key] = human_scores[i][key]
                    system_keys = model_scores['newsroom'][metric][approach].keys()
                    for key in system_keys:
                        system_scores[approach][i][metric][key] = model_scores['newsroom'][metric][approach][key][i]
    return system_scores


def system_judge(scores, metrics_human, metrics_system, correlation_types) -> dict:
    # ref: suenes.human.newsroom.test_eval
    all_system_names = list(scores[list(scores.keys())[0]].keys())

    def get_correlation_two_metrics(scores, metric_human, metric_system, correlation_type):
        mean_score_vector_newsroom = []
        mean_score_vector_other = []
        for system in all_system_names:
            vector_human = []  # scores from a human metric
            vector_system = []  # scores from a non-human metric
            for docID in scores.keys():
                score_local = scores[docID][system]
                score_newsroom = score_local[metric_human]  # one float
                score_other = score_local[metric_system]  # one float
                vector_human.append(score_newsroom)
                vector_system.append(score_other)

            mean_score_vector_newsroom.append(np.mean(vector_human))
            mean_score_vector_other.append(np.mean(vector_system))
        return eval(f"scipy.stats.{correlation_type}(vector_human, vector_system)")[0]

    # now begins the system-level judge
    correlations = {}
    for correlation_type in correlation_types:
        correlations[correlation_type] = {}
        for metric_human in metrics_human:  # one metric from human
            for metric_system in metrics_system:  # one metric to evaluate against human
                correlations[correlation_type] \
                    [(metric_human, metric_system)] = \
                    get_correlation_two_metrics(scores, metric_human, metric_system, correlation_type)

    return correlations


def realsumm_read(metrics: list) -> dict:
    _, _, _, dataset_scores = realsumm.read('suenes/human/realsumm/scores_dicts/',
                                            'suenes/human/realsumm/analysis/test.tsv')
    system_scores = dict()
    for approach in approaches:
        system_scores[approach] = dict()
        for i in range(len(dataset_scores)):
            system_scores[approach][i] = dict()
            for metric in metrics:
                system_scores[approach][i][metric] = dict()
                system_scores[approach][i][metric]['litepyramid_recall'] = dataset_scores[i][
                    'litepyramid_recall']  # human score
                system_keys = model_scores['realsumm'][metric]['trad'].keys()
                for key in system_keys:
                    system_scores[approach][i][metric][key] = model_scores['realsumm'][metric][approach][key][i]
    return system_scores


def calculate(dataset: str) -> None:
    corr[dataset] = dict()
    available_metrics_systems = {
        'rouge': ['rouge1', 'rouge2', 'rougeL', 'rougeLsum'],
        'bertscore': ['bertscore'],
        'bleurt': ['bleurt']
    }
    for id in range(len(available_metrics_systems.keys())):
        metric_systems_name = list(available_metrics_systems.keys())[id]
        metric_systems = available_metrics_systems[metric_systems_name]
        if dataset == 'newsroom':
            system_scores = newsroom_read(metric_systems)
            metrics_human = ['Coherence', 'Informativeness', 'Fluency', 'Relevance']
        elif dataset == 'realsumm':
            system_scores = realsumm_read(metric_systems)
            metrics_human = ['litepyramid_recall']
        else:
            raise NotImplementedError()
        if metric_systems_name == 'bleurt':
            metrics_system = ['scores']
        else:
            metrics_system = ['precision', 'recall', 'f1']
        correlation_types = ['pearsonr', 'kendalltau', 'spearmanr']
        my_corr = dict()
        for approach in approaches:
            my_corr[approach] = system_judge(system_scores[approach], metrics_human, metrics_system,
                                             correlation_types)
        corr[dataset][metric_systems_name] = my_corr


if __name__ == '__main__':
    model_scores = read_system_scores()
    datasets = ['newsroom', 'realsumm']
    for dataset in datasets:
        calculate(dataset)
    with open('results/model/corr.pkl', 'wb') as outfile:
        pickle.dump(corr, outfile)