# Test branch — measure the embedding read cost (#89 / #96)

A **Neon branch** off the prod project (`branch_name`, default `test`): isolated,
copy-on-write, so it inherits the prod schema *and* data for free while keeping
the measurement's writes off prod.

That's all this root creates. You run polymnemo **locally** against the branch
with `POLYMNEMO_LOG_LEVEL=DEBUG` and read the #96 observe lines off stdout.

> **Why not a deployed test app?** `_observe` computes the byte figure
> arithmetically (`len(rows) * embed_dim * 4`) rather than sampling the wire, so
> the numbers come out identical wherever the server runs. A Container App would
> add an Azure environment quota, a second public endpoint holding a copy of prod
> data, and a ~3-minute Log Analytics ingestion lag — for zero extra fidelity.

## Apply

`deploy (azure)` applies this root for you (the `test` job, beside `azure`), so a
release keeps the branch in place. To apply it by hand — Prereqs: the `neon/` root
is applied (this reads its state for the project id):

```sh
cp terraform.tfvars.example terraform.tfvars   # neon_api_key, tfstate_*
terraform init \
  -backend-config=resource_group_name=<rg> \
  -backend-config=storage_account_name=<sa> \
  -backend-config=container_name=tfstate \
  -backend-config=key=test.tfstate
terraform apply
```

> The branch is copy-on-write **at creation**. Once it exists Terraform leaves it
> alone, so a later `schema.sql` change does not reach it — `terraform destroy`
> and re-apply to pick one up.

## Measure (before vs after #89)

Run the server against the branch, in its own terminal:

```sh
export POLYMNEMO_DATABASE_URL="$(terraform output -raw database_url)"
export POLYMNEMO_LOG_LEVEL=DEBUG
export POLYMNEMO_API_KEYS="testkey:tester"
polymnemo 2>&1 | tee /tmp/polymnemo-debug.log
```

Then drive it and collect, from another terminal:

```sh
python scripts/measure_test_env.py \
  --key testkey --log /tmp/polymnemo-debug.log --out before.json
```

The script seeds once, replays the cases in `scripts/read_payload_cases.csv`, and
saves the parsed observe records. Do that on **main** (no defer) for `before.json`,
then check out the **#89 defer branch**, restart the server, and repeat for
`after.json`.

Compare: every read flips from `fetched (~N bytes)` to `deferred (~0)`. The
difference in total bytes per op is the transfer #89 saves.

## Tear down

```sh
terraform destroy   # drops the Neon branch + its endpoint
```
