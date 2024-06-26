import argparse
import datetime
import json
import subprocess

import requests
from google.cloud import storage


def read_json_file(file_path):
    with open(file_path, "r", encoding="utf-8") as file:
        return json.load(file)


def post_json_to_server(json_data, url):
    return requests.post(url, json=json_data)


def get_status(prompt_id, url):
    response = requests.get(f"{url}/{prompt_id}")
    if response.status_code == 200:
        return response.json()
    return None


def is_completed(status_response, prompt_id):
    # Check if the expected fields exist in the response
    return (
        status_response
        and prompt_id in status_response
        and "status" in status_response[prompt_id]
        and status_response[prompt_id]["status"].get("completed", False)
    )


def upload_to_gcs(bucket_name: str, destination_blob_name: str, source_file_name: str):
    print(
        f"Uploading file {source_file_name} to GCS bucket {bucket_name} as {destination_blob_name}"
    )
    storage_client = storage.Client()
    bucket = storage_client.get_bucket(bucket_name)

    blob = bucket.blob(destination_blob_name)
    blob.upload_from_filename(source_file_name)
    print(f"File {source_file_name} uploaded to {destination_blob_name}")


def send_payload_to_api(
    args, output_files_gcs_paths, workflow_name, start_time, end_time
):

    # Create the payload as a dictionary
    payload = {
        "repo": args.repo,
        "run_id": args.run_id,
        "os": args.os,
        "cuda_version": args.cuda_version,
        "output_files_gcs_paths": output_files_gcs_paths,
        "commit_hash": args.commit_hash,
        "commit_time": args.commit_time,
        "commit_message": args.commit_message,
        "branch_name": args.branch_name,
        "bucket_name": args.gsc_bucket_name,
        "workflow_name": workflow_name,
        "start_time": start_time,
        "end_time": end_time,
    }

    # Convert payload dictionary to a JSON string
    payload_json = json.dumps(payload)

    # Send POST request
    headers = {"Content-Type": "application/json"}
    response = requests.post(args.api_endpoint, headers=headers, data=payload_json)

    # Write response to application.log
    log_file_path = "./application.log"
    with open(log_file_path, "w", encoding="utf-8") as log_file:
        log_file.write("\n##### Comfy CI Post Response #####\n")
        log_file.write(response.text)

    # Check the response code
    if response.status_code != 200:
        print(
            f"API request failed with status code {response.status_code} and response body"
        )
        print(response.text)
        exit(1)
    else:
        print("API request successful")

    return response.status_code


def main(args):
    # Split the workflow file names using ","
    workflow_files = args.comfy_workflow_names.split(",")
    print("Running workflows ")
    counter = 1

    for workflow_file_name in workflow_files:
        # Construct the file path
        file_path = f"workflows/{workflow_file_name}"
        print(f"Running workflow {file_path}")
        start_time = int(datetime.datetime.now().timestamp())
        try:
            result = subprocess.run(
                ["comfy", "run", "--workflow", file_path],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            print("Output:", result.stdout)
        except subprocess.CalledProcessError as e:
            print("Error STD Out:", e.stdout)
            print("Error:", e.stderr)
            raise e

        print(f"Workflow {file_path} completed")
        end_time = int(datetime.datetime.now().timestamp())

        # TODO: add support for multiple file outputs
        gs_path = f"output-files/{args.github_action_workflow_name}-{args.os}-{workflow_file_name}-run-${args.run_id}"
        upload_to_gcs(
            args.gsc_bucket_name,
            gs_path,
            f"{args.workspace_path}/output/{args.output_file_prefix}_{counter:05}_.png",
        )

        send_payload_to_api(args, gs_path, workflow_file_name, start_time, end_time)
        counter += 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Send a JSON file contents to a server as a prompt."
    )
    parser.add_argument("--api-endpoint", type=str, help="API endpoint.")
    parser.add_argument(
        "--comfy-workflow-names", type=str, help="List of comfy workflow names."
    )
    parser.add_argument(
        "--github-action-workflow-name", type=str, help="Github action workflow name."
    )
    parser.add_argument("--os", type=str, help="Operating system.")
    parser.add_argument("--run-id", type=str, help="Github Run ID.")
    parser.add_argument("--repo", type=str, help="Github repo.")
    parser.add_argument("--cuda-version", type=str, help="CUDA version.")
    parser.add_argument("--commit-hash", type=str, help="Commit hash.")
    parser.add_argument("--commit-time", type=str, help="Commit time.")
    parser.add_argument("--commit-message", type=str, help="Commit message.")
    parser.add_argument("--branch-name", type=str, help="Branch name.")
    parser.add_argument(
        "--gsc-bucket-name",
        type=str,
        help="Name of the GCS bucket to store the output files in.",
    )
    parser.add_argument(
        "--workspace-path",
        type=str,
        help="Workspace (ComfyUI repo) path, likely ${HOME}/action_runners/_work/ComfyUI/ComfyUI/.",
    )
    parser.add_argument(
        "--action-path",
        type=str,
        help="Action path., likely ${HOME}/action_runners/_work/comfy-action/.",
    )
    parser.add_argument("--output-file-prefix", type=str, help="Output file prefix.")

    args = parser.parse_args()
    main(args)
