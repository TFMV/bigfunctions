import os
import shutil

import yaml
import jinja2

from .utils import bigquery, print_success


PYTHON_BUILD_DIR = 'build_python'
TEMPLATE_FOLDER = os.path.dirname(os.path.realpath(__file__)).replace('\\', '/') + '/templates'


def deploy(fully_qualified_bigfunction):
    project, dataset, bigfunction = fully_qualified_bigfunction.split('.')
    fully_qualified_dataset = f'{project}.{dataset}'
    bigfunction = fully_qualified_bigfunction.split('.')[-1]
    filename = f'bigfunctions/{bigfunction}.yaml'
    conf = yaml.safe_load(open(filename, encoding='utf-8').read().replace('{BIGFUNCTIONS_DATASET}', fully_qualified_dataset))

    if 'template' in conf:
        conf['code'] += f'''
            create or replace temp table bigfunction_result as
            select
                (select json from bigfunction_result) as json,
                (select {fully_qualified_dataset}.render_string(
                    """
                    {conf['template']}
                    """,
                    to_json_string(json)
                )
                from bigfunction_result) as html
            ;
        '''
    conf['libraries'] = [
        {
            'source_url': library,
            # 'filename': library.replace('https://', '').replace('http://', '').split('/', 1)[1],
            'cloudstorage_url': f"gs://bigfunctions_js_libs/{library}",
        }
        for library in conf.get('libraries', [])
    ]

    if conf['type'] == 'function_py':
        if os.path.exists(PYTHON_BUILD_DIR):
            shutil.rmtree(PYTHON_BUILD_DIR)
        os.makedirs(PYTHON_BUILD_DIR)

        template_file = f'{TEMPLATE_FOLDER}/{conf["type"]}.py'
        template = jinja2.Template(open(template_file, encoding='utf-8').read())
        python_code = template.render(**conf)
        with open(f'{PYTHON_BUILD_DIR}/main.py', 'w', encoding='utf-8') as out:
            out.write(python_code)

        with open(f'{PYTHON_BUILD_DIR}/requirements.txt', 'w', encoding='utf-8') as out:
            out.write('gunicorn\nflask\ngoogle-cloud-error-reporting\n' + conf['requirements'])

        shutil.copy(f'{TEMPLATE_FOLDER}/Dockerfile', PYTHON_BUILD_DIR)

        deploy_command = f'gcloud run deploy {bigfunction.replace("_", "-")} --source {PYTHON_BUILD_DIR} --region europe-west1 --project {project} --no-allow-unauthenticated'
        print(f'deploying cloud run {bigfunction} with command `{deploy_command}`')
        os.system(deploy_command)

        add_invoker_role_command = f'gcloud run services add-iam-policy-binding {bigfunction.replace("_", "-")} --region europe-west1 --member=serviceAccount:bqcx-749389685934-ielt@gcp-sa-bigquery-condel.iam.gserviceaccount.com --role=roles/run.invoker'
        print(f'giving invoker permission to connection service account with command `{add_invoker_role_command}`')
        os.system(add_invoker_role_command)

        conf['remote_connection'] = '749389685934.eu.remote-bigfunctions'
        conf['remote_endpoint'] = f'https://{bigfunction.replace("_", "-")}-ccbxjzt67q-ew.a.run.app'

    template_file = f'{TEMPLATE_FOLDER}/{conf["type"]}.sql'
    template = jinja2.Template(open(template_file, encoding='utf-8').read())
    query = template.render(
        dataset=fully_qualified_dataset,
        name=bigfunction,
        filename=filename,
        **conf,
    )
    bigquery.query(query)
    print_success('successfully created ' + fully_qualified_bigfunction)


