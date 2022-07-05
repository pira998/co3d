# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

import os
import zipfile
import glob
import logging

from tqdm import tqdm
from collections import defaultdict
from typing import List, Dict
from .data_types import CO3DSequenceSet, CO3DTask
from .metric_utils import eval_one, EVAL_METRIC_NAMES
from .io import load_rgbda_frame


logger = logging.getLogger(__file__)


def get_co3d_task_from_subset_name(subset_name: str) -> CO3DTask:
    if subset_name.startswith("manyview"):
        return CO3DTask.MANY_VIEW
    elif subset_name.startswith("fewview"):
        return CO3DTask.FEW_VIEW
    else:
        raise ValueError(f"Invalid subset name {subset_name}!")


def get_co3d_sequence_set_from_subset_name(subset_name: str) -> CO3DSequenceSet:
    return CO3DSequenceSet(subset_name.split("_")[1])


def unzip(file_path: str, output_dir: str):
    with zipfile.ZipFile(file_path, "r") as zip_ref:
        zip_ref.extractall(output_dir)


def check_user_submission_file_paths(
    ground_truth_files: Dict[str, str],
    user_submission_files: Dict[str, str],
):
    missing_gt_examples = [
        gt_example_name
        for gt_example_name in ground_truth_files
        if gt_example_name not in user_submission_files
    ]
    if len(missing_gt_examples) > 0:
        raise ValueError(
            f"There are missing evaluation examples: {str(missing_gt_examples)}"
        )

    additional_user_examples = [
        user_example
        for user_example in user_submission_files
        if user_example not in ground_truth_files
    ]
    if len(additional_user_examples) > 0:
        raise ValueError(
            f"Unexpected submitted evaluation examples {str(additional_user_examples)}"
        )


def get_result_directory_file_names(
    result_dir: str, has_depth_masks: bool = False,
) -> Dict[str, str]:
    """
    Result directory structure:
        <test_example_name>_image.png
        <test_example_name>_mask.png
        <test_example_name>_depth.png
        ...

    Returns:
        result_files: dict {test_example_name_i: root_path_i}
    """

    result_type_files = {}
    for result_type in ("image", "mask", "depth"):
        postfix = f"_{result_type}.png"
        matching_files = sorted(glob.glob(os.path.join(result_dir, f"*{postfix}")))
        if has_depth_masks and result_type=="mask":
            matching_files = [f for f in matching_files if not f.endswith("_depth_mask.png")]
        result_type_files[result_type] = {
            os.path.split(f)[-1][: -len(postfix)]: f for f in matching_files
        }

    example_names = sorted(
        list(
            set(
                [
                    n
                    for t in ("image", "mask", "depth")
                    for n in result_type_files[t].keys()
                ]
            )
        )
    )

    missing_examples = defaultdict(list)
    for example_name in example_names:
        for result_type in ("image", "mask", "depth"):
            if example_name not in result_type_files[result_type]:
                missing_examples[example_name].append(result_type)

    if len(missing_examples) > 0:
        msg = "\n".join(
            [f"   {k} missing {str(v)}" for k, v in missing_examples.items()]
        )
        raise ValueError("Some evaluation examples are incomplete:\n" + msg)

    result_files = {
        example_name: result_type_files["image"][example_name][: -len("_image.png")]
        for example_name in example_names
    }

    return result_files


def evaluate_file_folders(pred_folder: str, gt_folder: str):
    user_submission_files = get_result_directory_file_names(pred_folder)
    ground_truth_files = get_result_directory_file_names(gt_folder, has_depth_masks=True)

    logger.info(f"Evaluating folders: prediction={pred_folder}; gt={gt_folder}")
    check_user_submission_file_paths(
        ground_truth_files,
        user_submission_files,
    )

    # At this point we are sure that ground_truth_files contain the same
    # examples as user_submission_files.

    # Iterate over the gt examples:
    per_example_results = [
        eval_one(
            load_rgbda_frame(ground_truth_files[gt_example]),
            load_rgbda_frame(user_submission_files[gt_example]),
        )
        for gt_example in tqdm(list(ground_truth_files))
    ]

    result = {
        metric: (sum(r[metric] for r in per_example_results) / len(per_example_results))
        for metric in EVAL_METRIC_NAMES
    }

    return result, per_example_results


def get_annotations_folder(phase_codename: str):
    assert phase_codename in {"dev", "test"}
    return os.path.join("annotations", phase_codename)
