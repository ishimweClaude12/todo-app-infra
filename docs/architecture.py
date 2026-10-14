"""Todo App network architecture, as code.

Render (needs Graphviz on PATH, e.g. `winget install graphviz`):
    uvx --with diagrams python docs/architecture.py
Writes docs/architecture.png.
"""
from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import ECR, ElasticContainerServiceService, Fargate
from diagrams.aws.database import ElasticacheForRedis, RDSPostgresqlInstance
from diagrams.aws.devtools import Codedeploy, Codepipeline
from diagrams.aws.integration import Eventbridge
from diagrams.aws.management import Cloudformation, Cloudwatch
from diagrams.aws.network import ALB, Endpoint, InternetGateway, RDSProxy
from diagrams.aws.security import IAMRole, SecretsManager
from diagrams.aws.storage import S3
from diagrams.onprem.ci import GithubActions
from diagrams.onprem.client import Users
from diagrams.onprem.vcs import Github

OUT = str(Path(__file__).with_name("architecture"))

graph_attr = {"fontsize": "20", "pad": "0.5", "splines": "spline", "nodesep": "0.6", "ranksep": "0.9"}

with Diagram("Todo App on ECS Fargate (us-east-1)", filename=OUT, show=False,
             direction="LR", graph_attr=graph_attr):
    users = Users("Users")

    with Cluster("CI/CD"):
        app_repo = Github("todo-app-codes")
        infra_repo = Github("todo-app-infra")
        gha = GithubActions("GitHub Actions\n(OIDC, no keys)")
        gitsync = Cloudformation("CloudFormation\nGit sync")

    with Cluster("AWS Region us-east-1"):
        ecr = ECR("ECR\ntodo-app-app")
        artifacts = S3("Artifact bucket\nconfig-source.zip")
        rule = Eventbridge("EventBridge\nECR push rule")
        pipeline = Codepipeline("CodePipeline")
        codedeploy = Codedeploy("CodeDeploy\nblue/green")
        secrets = SecretsManager("Secrets Manager\nDB + Redis AUTH")
        logs = Cloudwatch("CloudWatch Logs")
        oidc_role = IAMRole("CI role")

        with Cluster("VPC 10.0.0.0/16 (2 AZs)"):
            igw = InternetGateway("IGW")

            with Cluster("Public subnets 10.0.0-1.0/24\nSG: alb-sg (80 from internet)"):
                alb = ALB("ALB\nblue / green TGs")

            with Cluster("App subnets 10.0.10-11.0/24\nSG: ecs-sg (3000 from alb-sg)"):
                tasks = [Fargate("task AZ-a"), Fargate("task AZ-b")]
                service = ElasticContainerServiceService("ECS service\nautoscale 1-4 on CPU")
                vpce = Endpoint("VPC endpoints\necr.api/dkr, logs,\nsecretsmanager, s3 gw\nSG: vpce-sg")

            with Cluster("Proxy subnets 10.0.30-31.0/24\nSG: rds-proxy-sg (5432 from ecs-sg)"):
                proxy = RDSProxy("RDS Proxy\nTLS required")

            with Cluster("Data subnets 10.0.20-21.0/24\nSG: rds-sg (5432 from proxy-sg)"):
                rds = RDSPostgresqlInstance("RDS PostgreSQL\ndb.t3.micro")

            with Cluster("Cache subnets 10.0.40-41.0/24\nSG: redis-sg (6379 from ecs-sg)"):
                redis = ElasticacheForRedis("ElastiCache Redis\nprimary + replica")

    # Request path
    users >> Edge(label="HTTP :80") >> igw >> alb >> Edge(label=":3000") >> tasks
    service - tasks
    tasks >> Edge(label="writes + misses :5432") >> proxy >> rds
    tasks >> Edge(label="cache-aside reads :6379", color="firebrick") >> redis
    tasks >> Edge(style="dashed", label="443") >> vpce
    vpce >> Edge(style="dashed") >> [ecr, secrets, logs]

    # Delivery path
    app_repo >> gha >> Edge(label="assume via OIDC") >> oidc_role
    gha >> Edge(label="push :sha, :latest") >> ecr
    gha >> Edge(label="taskdef + appspec") >> artifacts
    ecr >> Edge(label="PUSH event") >> rule >> pipeline
    artifacts >> pipeline >> codedeploy >> Edge(label="shift traffic") >> alb
    infra_repo >> gitsync
