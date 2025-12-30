from gql import Client, gql
from gql.transport.requests import RequestsHTTPTransport

def fetch_experiment_details(gql_client, dataset_id):
    experiments_query = gql(
        """
        query getExperimentDetails($DatasetId:ID!){
        node(id: $DatasetId) {
            ... on Dataset {
            name
            experiments(first: 1){
                edges{
                node{
                    name
                    createdAt
                    evaluationScoreMetrics{
                        name
                        meanScore
                    }
                }
                }
            }
            }
        }
        }
        """
    )

    params = {"DatasetId": dataset_id}
    response = gql_client.execute(experiments_query, params)
    experiments = response["node"]["experiments"]["edges"]
    
    experiments_list = []
    for experiment in experiments:
        node = experiment["node"]
        experiment_name = node["name"]
        for metric in node["evaluationScoreMetrics"]:
            experiments_list.append([
                experiment_name,
                metric["name"],
                metric["meanScore"]
            ])
    
    return experiments_list


def determine_experiment_success(experiment_result):
    success = experiment_result > 0.7
    sys.exit(0 if success else 1)