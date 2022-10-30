import json

import evaluate
import pandas

import functools
import env
import numpy, scipy

import sys
sys.path.append("../")
import bertscore_sentence.eval as bertscore_sentence

import typing 
import tqdm


# TODO 
# ref_{free,based}_metrics is a dict {str:function}
# ref_based_metrics = {
#     "bleurt": evaluate.load('bleurt', config_name='BLEURT-20', module_type='metric'), 
#     "rouge": functools.partial( evaluate.load("rouge"), use_aggregator=False)

#     }

# ref_free_metrics = {    
#     "bertscore-sentence": bertscore_sentence
# }
# all metrics shall return a dict {metric_name: List[float]}


def model_eval(
    sys_summaries: list, 
    ref_summaries: list, 
    docs: list, 
    models: typing.List[str], 
    approaches: typing.List[str]) -> pandas.DataFrame:
    """Given a batch of samples, run various automated summary metrics to evaluate the quality of summaries. 
    """
    
    # Create a placeholder multiindex Dataframe
    # Each row corresponds to one (doc, sys) or (ref, sys) pair, i.e., one sample. 
    # columns are the metrics nested in 3 levels (approach, model, score_name). 
    index= pandas.MultiIndex.from_tuples([], names = ["approach", "model", "score_name"])
    batch_result_df = pandas.DataFrame((), columns =index)

    for model_name in models:
        # print('Model: ' + model_name)
        if model_name == 'bleurt':
            model = evaluate.load('bleurt', config_name='BLEURT-20', module_type='metric')
        elif model_name == 'bertscore-sentence':
            model = bertscore_sentence
        else:
            model = evaluate.load(model_name)

        # calculate traditional (reference, system summary) pairs and new (document, system summary) pairs
        for approach in approaches:
            # print('Evaluating on ' + approach + ' approach')
            cands = sys_summaries
            refs = ref_summaries if approach == "trad" else docs
            if model_name == 'bertscore':
                model_result = model.compute(predictions=cands, references=refs, lang='en', use_fast_tokenizer=True)
            elif model_name == 'rouge':
                model_result = model.compute(predictions=cands, references=refs, use_aggregator=False)
            elif model_name == 'bertscore-sentence':
                model_result = model.compute(predictions=cands, references=refs)
            else:
                model_result = model.compute(predictions=cands, references=refs)

            # model_result is a dict, e.g., {'ROUGE-1': [0.1, 0.9, 0.8], 'ROUGE-2':[0.5, 0.7 0.8]} each item in a value-list corresponds to a (doc, sys summ) pair  or a (ref summ, sys summ) pair. 
            for score_name, score_list in model_result.items():
                if score_name != "hashcode":
                    batch_result_df[approach, model_name, score_name] = score_list

    return batch_result_df

def batched_corr(corr_df, human_scores, batch_result_df, corr_metrics, batchID):
    """Compute the correlations between human scores and automated metric scores on batch of samples, each of which is a pair of (doc, sys summ) or (ref summ, sys summ)

    Iteratively add rows to corr_df. 
    """

    corr_metric_mapping = {"pearsonr": scipy.stats.pearsonr, "spearmanr": scipy.stats.spearmanr}
    for corr_metric in corr_metrics:
        for aspect_name, human_score in human_scores.iteritems(): 
            for (approach, model, score_name) in batch_result_df.columns:
                metric_score = batch_result_df[(approach, model, score_name)]
                # FIXME: Why cannot I use the f-string below? 
                # cc = eval(f"scipy.stats.{corr_metric}")(human_score, metric_score)[0]

                cc =  corr_metric_mapping[corr_metric](human_score, metric_score)[0]

                corr_df.loc[
                    (corr_metric, aspect_name, approach, model, score_name),  # row
                    batchID 
                    ] = cc 
    return  corr_df

def pool_multidoc(batch_df: pandas.DataFrame, result_df: pandas.DataFrame):
    """Pool muiltidocument evaluation results 
    """
    docsetID_and_System = batch_df[['docsetID', 'System']]
    # print (docsetID_and_System.shape, result_df.shape)

    docsetID_and_System = docsetID_and_System.reset_index(drop=True) 
    # reset index from 0 because batch_df's index is a segment of a much longer index range 
    # if not reset index, cannot concat below without ignore_index due to misaligned indexes 
    # We do not use ignore_index below because it will otherwise reset multiindex column headers to 0 to N. 
    combined = pandas.concat([docsetID_and_System, result_df], axis=1)


    combined_pooled = combined.groupby(['docsetID', 'System']).mean()
    # combined_pooled = combined_pooled.drop(["index", 'docsetID', 'System'], axis=1)

    # Drop scores of the common summary
    human_scores = batch_df.drop(['ArticleText', 'ReferenceSummary',
       'SystemSummary'], axis=1)
    human_scores = batch_df.groupby(['docsetID', 'System']).mean() 

    
    # print (batch_df_new.shape, combined_pooled.shape)

    # The returned DataFrame does not have multi-indexed columns but has tuples as column names 
    return human_scores, combined_pooled

# TODO: Default value shouldn't be tied to env 
def eval_summary_level(
    dataset_df:pandas.DataFrame, 
    exp_approaches: typing.List[str] = env.approaches,
    exp_models: typing.List[str]    = env.models,
    corr_metrics: typing.List[str]  = env.corr_metrics, 
    document_column: str            = env.document_column, 
    docID_column: str               = env.docID_column,  # TODO: some in newsroom, realsumm, summeval have not supported this yet 
    system_summary_column: str      = env.system_summary_column, 
    reference_summary_column: str   = env.reference_summary_column, 
    human_metrics: typing.List[str] = env.human_metrics, 
    pre_calculated_metrics: typing.List[str] = [], # some datasets contain metric scores 
    debug = False, 
    is_multi = False, # multi-document summarization
):
    """Get summary-level scores for system summaries using various scoring methods. 

    Summary-level evaluation means that we compute corraltion for each document and then average across documents. For its definitions, see Eq. (1) of RealSumm paper EMNLP 2020 https://aclanthology.org/2020.emnlp-main.751.pdf 

    """

    # batching based on articles. Also saves memory. 
    # for articleID in df["ArticleID"].unique(): # summary-level, we so need to loop over articles 
    #     print (articleID)
    #     batch = df [ df["ArticleID"] == articleID] 

    index = pandas.MultiIndex.from_tuples(
        [], 
        names = ["corr_metric", "aspect", "approach", "model", "score_name"])
    corr_df = pandas.DataFrame((), index= index)
    # each COLUMN corresponds to one document/batchs
    # An Index (per row) is nested in 5 levels: 
    # (corr_metric, aspect, approach, model, score_name)
    # 
    # At the end, just average every row (axis=1)
    # We could let the multilevel on columns,
    #  but the code will be slightly longer.

    for batchID, docID in enumerate(tqdm.tqdm ( dataset_df[docID_column].unique())):

        if debug: 
            if batchID > 2 : 
                break 

        batch = dataset_df [ dataset_df[docID_column] == docID]
        # without .to_numpy(), will run into issues starting from 2nd iteration 
        docs   = batch[document_column].to_numpy()
        sys_summs  = batch[system_summary_column].to_numpy()
        ref_summs   = batch[reference_summary_column].to_numpy()
        human_scores = batch[human_metrics] # a DF

        batch_result_df = model_eval(sys_summs, ref_summs, docs, exp_models, exp_approaches)

        if is_multi: # average the scores for multiple documents to the same reference 
            human_scores, batch_result_df = pool_multidoc(batch, batch_result_df)

        # batch_result_df[approach, model, score_name] ===> a list for each pair in the batch 

        # Insert precalculated metrics 
        if isinstance(pre_calculated_metrics, list) and len(pre_calculated_metrics)> 0: 
            for score_name in pre_calculated_metrics: 
                batch_result_df["PreCalc","PreCalc",score_name] = batch[score_name].to_numpy()

        corr_df = batched_corr(corr_df, human_scores, batch_result_df, corr_metrics, batchID)

    final_corr_df = corr_df.mean(axis=1)
    corr_df['average'] = final_corr_df # last column 

    return corr_df


def eval_system_level():
    """Get system-level scores for system summaries using various scoring methods. 

    System-level evaluation means that we compute corraltion for each system and then average across systems

    """

    pass