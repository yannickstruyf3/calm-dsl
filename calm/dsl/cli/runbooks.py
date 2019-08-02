import time
import warnings
import importlib.util
import datetime

import arrow
import click
from prettytable import PrettyTable

from calm.dsl.builtins import RunbookService, create_runbook_payload
from calm.dsl.config import get_config
from .utils import get_name_query, highlight_text


def get_runbook_list(obj, name, filter_by, limit, offset, quiet, all_items):
    """Get the runbooks, optionally filtered by a string"""

    client = obj.get("client")
    config = obj.get("config")

    params = {"length": limit, "offset": offset}
    filter_query = ""
    if name:
        filter_query = get_name_query([name])
    if filter_by:
        filter_query = filter_query + ";" + filter_by if name else filter_by

    # TODO
    # if all_items:
    #    filter_query += get_states_filter(BLUEPRINT.STATES)
    if filter_query.startswith(";"):
        filter_query = filter_query[1:]

    if filter_query:
        params["filter"] = filter_query

    res, err = client.runbook.list(params=params)

    if err:
        pc_ip = config["SERVER"]["pc_ip"]
        warnings.warn(UserWarning("Cannot fetch blueprints from {}".format(pc_ip)))
        return

    json_rows = res.json()["entities"]

    if quiet:
        for _row in json_rows:
            row = _row["status"]
            click.echo(highlight_text(row["name"]))
        return

    table = PrettyTable()
    table.field_names = [
        "NAME",
        "DESCRIPTION",
        "RUN COUNT",
        "CREATED ON",
        "LAST UPDATED",
        "UUID",
    ]
    for _row in json_rows:
        row = _row["status"]
        metadata = _row["metadata"]

        creation_time = int(metadata["creation_time"]) // 1000000
        last_update_time = int(metadata["last_update_time"]) // 1000000

        table.add_row(
            [
                highlight_text(row["name"]),
                highlight_text(row["description"]),
                highlight_text(row["run_count"]),
                highlight_text(time.ctime(creation_time)),
                "{}".format(arrow.get(last_update_time).humanize()),
                highlight_text(row["uuid"]),
            ]
        )
    click.echo(table)


def get_runbook_module_from_file(runbook_file):
    """Return Runbook module given a user runbook dsl file (.py)"""

    spec = importlib.util.spec_from_file_location("calm.dsl.user_bp", runbook_file)
    user_runbook_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(user_runbook_module)

    return user_runbook_module


def get_runbook_class_from_module(user_runbook_module):
    """Returns blueprint class given a module"""

    UserRunbook = None
    for item in dir(user_runbook_module):
        obj = getattr(user_runbook_module, item)
        if isinstance(obj, type(RunbookService)):
            if obj.__bases__[0] is RunbookService:
                UserRunbook = obj

    return UserRunbook


def compile_runbook(runbook_file):

    user_runbook_module = get_runbook_module_from_file(runbook_file)
    UserRunbook = get_runbook_class_from_module(user_runbook_module)
    if UserRunbook is None:
        return None

    runbook_payload = None
    UserRunbookPayload, _ = create_runbook_payload(UserRunbook)
    runbook_payload = UserRunbookPayload.get_dict()

    return runbook_payload


def get_previous_runs(obj, name, filter_by, limit, offset, quiet, all_items):
    client = obj.get("client")
    config = obj.get("config")

    params = {"length": limit, "offset": offset}
    filter_query = ""
    if name:
        filter_query = get_name_query([name])
    if filter_by:
        filter_query = filter_query + ";" + filter_by if name else filter_by
    # if all_items:
    #    filter_query += get_states_filter(APPLICATION.STATES, state_key="_state")
    if filter_query.startswith(";"):
        filter_query = filter_query[1:]

    if filter_query:
        params["filter"] = filter_query

    res, err = client.runbook.list_previous_runs(params=params)

    if err:
        pc_ip = config["SERVER"]["pc_ip"]
        warnings.warn(UserWarning("Cannot fetch previous runs from {}".format(pc_ip)))
        return

    json_rows = res.json()["entities"]

    if quiet:
        for _row in json_rows:
            row = _row["status"]
            click.echo(highlight_text(row["action_reference"]["name"]))
        return

    table = PrettyTable()
    table.field_names = [
        "SOURCE RUNBOOK",
        "STATE",
        "OWNER",
        "CREATED ON",
        "LAST UPDATED",
        "UUID",
    ]
    for _row in json_rows:
        row = _row["status"]
        metadata = _row["metadata"]

        creation_time = int(metadata["creation_time"]) // 1000000
        last_update_time = int(metadata["last_update_time"]) // 1000000

        table.add_row(
            [
                highlight_text(row["action_reference"]["name"]),
                highlight_text(row["state"]),
                highlight_text(row["userdata_reference"]["name"]),
                highlight_text(time.ctime(creation_time)),
                "{}".format(arrow.get(last_update_time).humanize()),
                highlight_text(metadata["uuid"]),
            ]
        )
    click.echo(table)


def get_runbook(client, name, all=False):

    # find runbook
    params = {"filter": "name=={}".format(name)}
    if not all:
        params["filter"] += ";deleted==FALSE"

    res, err = client.runbook.list(params=params)
    if err:
        raise Exception("[{}] - {}".format(err["code"], err["error"]))

    response = res.json()
    entities = response.get("entities", None)
    runbook = None
    if entities:
        if len(entities) != 1:
            raise Exception("More than one runbook found - {}".format(entities))

        click.echo(">> {} found >>".format(name))
        runbook = entities[0]
    else:
        raise Exception(">> No runbook found with name {} found >>".format(name))
    return runbook


def run_runbook(
    client,
    runbook_name,
    runbook=None,
):
    if not runbook:
        runbook = get_runbook(client, runbook_name)

    runbook_uuid = runbook.get("metadata", {}).get("uuid", "")

    res, err = client.runbook.run(runbook_uuid, {})
    if not err:
        click.echo(">> {} queued for run".format(runbook_name or "Runbook"))
    else:
        raise Exception("[{}] - {}".format(err["code"], err["error"]))
    response = res.json()
    runlog_uuid = response["status"]["runlog_uuid"]

    # Poll every 10 seconds on the app status, for 5 mins
    maxWait = 5 * 60
    count = 0
    while count < maxWait:
        # call status api
        res, err = client.runbook.poll_action_run(runlog_uuid)
        if err:
            raise Exception("[{}] - {}".format(err["code"], err["error"]))

        response = res.json()
        click.echo("[{}] Runbook run is in {} state. Runlog uuid is: {}".format(
            highlight_text(str(datetime.datetime.now())), highlight_text(response["status"]["state"]), highlight_text(runlog_uuid)
        ))
        if response["status"]["state"] == "SUCCESS":
            config = get_config()
            pc_ip = config["SERVER"]["pc_ip"]
            pc_port = config["SERVER"]["pc_port"]

            click.echo("[{}] Successfully ran Runbook. Runlog uuid is: {}".format(highlight_text(str(datetime.datetime.now())), highlight_text(runlog_uuid)))

            click.echo(">> run completed".format(runbook_name or "Runbook"))
            run_url = "https://{}:{}/console/#page/explore/calm/runs/{}?runbookId={}".format(pc_ip, pc_port, runlog_uuid, runbook_uuid)
            click.echo("\nRunbook run url: {}".format(highlight_text(run_url)))
            describe_runlog(client, runlog_uuid)
            break
        elif response["status"]["state"] == "FAILURE" or response["status"]["state"] == "SYS_ERROR":
            click.echo("[{}] Failed to run runbook -".format(str(datetime.datetime.now())))
            for reason in response["status"]["reason_list"]:
                click.echo("\tERROR: {}".format(str(reason)))
            click.echo(">> run completed".format(runbook_name or "Runbook"))
            run_url = "https://{}:{}/console/#page/explore/calm/runs/{}?runbookId={}".format(pc_ip, pc_port, runlog_uuid, runbook_uuid)
            click.echo("\nRunbook run url: {}".format(highlight_text(run_url)))
            describe_runlog(client, runlog_uuid)
            break
        count += 10
        time.sleep(10)


def describe_runlog(client, uuid, level=0):
    res, err = client.runbook.poll_action_run(uuid)
    if err:
        raise Exception("[{}] - {}".format(err["code"], err["error"]))

    response = res.json()
    if response['status']['type'] == 'action_runlog':
        click.echo("\n---------Runbook Run Recap-----------\n")
        click.echo("\n{} [{}]".format(response['status']['action_reference']['name'], highlight_text(response['status']['state'])))

    res, err = client.runbook.list_runlogs(uuid)
    if err:
        raise Exception("[{}] - {}".format(err["code"], err["error"]))
    response = res.json()

    level += 1
    indent = "\t" * level
    for entity in response['entities']:
        runlog_uuid = entity['metadata']['uuid']
        if entity['status']['type'] == 'task_runlog':
            click.echo("{}{} [{}]".format(indent, entity['status']['task_reference']['name'], highlight_text(entity['status']['state'])))
            res, err = client.runbook.runlog_output(runlog_uuid)
            if err:
                raise Exception("\n{}[{}] - {}".format(indent, err["code"], err["error"]))
            runlog_output = res.json()
            for output in runlog_output['status']['output_list']:
                output_lines = str(output['output']).splitlines()
                click.echo("{}---------------------------------".format(indent))
                for line in output_lines:
                    click.echo("{}{}".format(indent, highlight_text(line)))
                click.echo("{}---------------------------------".format(indent))
        elif entity['status']['type'] == 'runbook_runlog':
            click.echo("\n{}{} [{}]".format(indent, entity['status']['runbook_reference']['name'], highlight_text(entity['status']['state'])))
            describe_runlog(client, runlog_uuid, level)
        else:
            describe_runlog(client, runlog_uuid, level)


def describe_runbook(obj, runbook_name):
    client = obj.get("client")
    runbook = get_runbook(client, runbook_name, all=True)

    res, err = client.runbook.read(runbook["metadata"]["uuid"])
    if err:
        raise Exception("[{}] - {}".format(err["code"], err["error"]))

    runbook = res.json()

    click.echo("\n----Runbook Summary----\n")
    click.echo(
        "Name: "
        + highlight_text(runbook_name)
        + " (uuid: "
        + highlight_text(runbook["metadata"]["uuid"])
        + ")"
    )
    click.echo("Description: " + highlight_text(runbook["status"]["description"]))
    click.echo("Status: " + highlight_text(runbook["status"]["state"]))
    click.echo(
        "Owner: " + highlight_text(runbook["metadata"]["owner_reference"]["name"])
    )

    created_on = int(runbook["metadata"]["creation_time"]) // 1000000
    past = arrow.get(created_on).humanize()
    click.echo(
        "Created: {} ({})".format(
            highlight_text(time.ctime(created_on)), highlight_text(past)
        )
    )
    runbook_resources = runbook.get("status").get("resources", {})

    click.echo("Runbook :")
    runbook_dict = runbook_resources.get("runbook", {})
    main_task = runbook_dict.get("main_task_local_reference", {})
    click.echo("\tMainTask: {}".format(highlight_text(main_task.get("name", ""))))

    task_list = runbook_dict.get("task_definition_list", [])
    click.echo("\tTasks [{}]:".format(highlight_text(len(task_list))))
    for task in task_list:
        task_name = task.get("name", "")
        task_type = task.get("type", "")
        click.echo("\t\t{} ({})".format(highlight_text(task_name), highlight_text(task_type)))

    variable_types = [
        var.get("name", "")
        for var in runbook_dict.get("variable_list", [])
    ]
    click.echo("\tVariables [{}]:".format(highlight_text(len(variable_types))))
    click.echo("\t\t{}".format(highlight_text(", ".join(variable_types))))

    substrate_types = [
        "{} ({})".format(sub.get("name", ""), sub.get("type", ""))
        for sub in runbook_resources.get("substrate_definition_list", [])
    ]

    click.echo("Substrates [{}]:".format(highlight_text(len(substrate_types))))
    click.echo("\t{}".format(highlight_text(", ".join(substrate_types))))

    credential_types = [
        "{} ({})".format(cred.get("name", ""), cred.get("type", ""))
        for cred in runbook_resources.get("credential_definition_list", [])
    ]
    click.echo("Credentials [{}]:".format(highlight_text(len(credential_types))))
    click.echo("\t{}".format(highlight_text(", ".join(credential_types))))


def delete_runbook(obj, runbook_names):

    client = obj.get("client")

    for runbook_name in runbook_names:
        runbook = get_runbook(client, runbook_name)
        runbook_id = runbook["metadata"]["uuid"]
        res, err = client.runbook.delete(runbook_id)
        if err:
            raise Exception("[{}] - {}".format(err["code"], err["error"]))
        click.echo("Runbook {} deleted".format(runbook_name))
