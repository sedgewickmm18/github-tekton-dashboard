"""
FalkorDB graph schema definitions for Tekton Pipeline Dashboard.

Nodes:
  - Pipeline   {pipeline_id, name, region, trigger_name}
  - Run        {run_id, build_number, status, created_at, updated_at, duration_seconds}
  - PR         {pr_number, title, author, url, created_at}
  - Commit     {sha}
  - Stage      {stage_id}             unique per pipeline+stage name combination
  - ErrorType  {name}
  - Developer  {login}

Relationships:
  - (Pipeline)-[:HAS_RUN]->(Run)
  - (Run)-[:BELONGS_TO_PR]->(PR)
  - (Run)-[:AUTHORED_BY]->(Developer)
  - (Run)-[:HAS_STAGE]->(Stage)
  - (Run)-[:HAS_ERROR]->(ErrorType)
  - (Run)-[:IS_RERUN_OF]->(Run)
  - (PR)-[:HAS_COMMIT]->(Commit)
"""

# Index definitions applied by migrate.py
INDEXES = [
    "CREATE INDEX ON :Run(run_id)",
    "CREATE INDEX ON :Run(created_at)",
    "CREATE INDEX ON :Run(build_number)",
    "CREATE INDEX ON :PR(pr_number)",
    "CREATE INDEX ON :Pipeline(pipeline_id)",
    "CREATE INDEX ON :Stage(stage_id)",
    "CREATE INDEX ON :ErrorType(name)",
    "CREATE INDEX ON :Developer(login)",
]
