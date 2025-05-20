eoapi-template
Template repository to deploy eoapi on AWS using the eoapi-cdk constructs or locally with Docker.

Requirements
python >=3.9
docker
node >=14
AWS credentials environment variables configured to point to an account.
Optional a config.yaml file to override the default deployment settings defined in config.py.
Installation
Install python dependencies with

python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
And node dependencies with

npm install
Verify that the cdk CLI is available. Since aws-cdk is installed as a local dependency, you can use the npx node package runner tool, that comes with npm.

npx cdk --version
Deployment
First, synthesize the app

npx cdk synth --all
Then, deploy

npx cdk deploy --all --require-approval never
Docker
Before deploying the application on the cloud, you can start by exploring it with a local Docker deployment

docker compose up
Once the applications are up, you'll need to add STAC Collections and Items to the PgSTAC database. If you don't have, you can use the follow the MAXAR open data demo (or get inspired by the other demos).

Then you can start exploring your dataset with:

the STAC Metadata service http://localhost:8081
the Raster service http://localhost:8082
the browser UI http://localhost:8085
If you've added a vector dataset to the public schema in the Postgres database, they will be available through the Vector service at http://localhost:8083.