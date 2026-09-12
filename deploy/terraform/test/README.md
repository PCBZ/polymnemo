# Test environment (DEBUG) — measure the embedding read cost via Log Analytics

A throwaway-ish **test env** for measuring what the embedding column costs on
reads (#89 / #96), without touching prod:

- a **Neon branch** off the prod project (`branch_name`, default `test`) — isolated,
  copy-on-write, so it inherits the prod schema (no `schema.sql` step);
- a **Container App** running the same public GHCR image with
  **`POLYMNEMO_LOG_LEVEL=DEBUG`**, so the #96 read-payload observe lines land in
  the module's Log Analytics workspace.

> ⚠️ This terraform is **not apply-tested**. In particular `local.test_dsn` is
> assembled from the Neon provider's role / password / pooled host — verify it on
> the first apply (a wrong DSN just means the test app can't reach the branch).

## Apply

Prereqs: the `neon/` root is applied (this reads its state for the project id).

```
cp terraform.tfvars.example terraform.tfvars   # neon_api_key, azure_subscription_id,
                                               # image, api_keys, tfstate_*
terraform init \
  -backend-config=resource_group_name=<rg> \
  -backend-config=storage_account_name=<sa> \
  -backend-config=container_name=tfstate \
  -backend-config=key=test.tfstate
terraform apply
terraform output -raw mcp_endpoint
```

## Measure (before vs after #89)

1. Deploy the **no-defer** image (before #89) here, exercise some reads
   (recall / list / get / a session load) against `mcp_endpoint`.
2. Deploy the **+defer** image (after #89), exercise the same reads.
3. Query the Log Analytics workspace (`<service_name>-logs`) with KQL and compare
   the two time windows:

```kusto
ContainerAppConsoleLogs_CL
| where ContainerAppName_s == "polymnemo-test"
| where Log_s startswith "read "
| parse Log_s with "read " op ": " rows:int " rows, embedding " state " (~" bytes:int " bytes)"
| summarize reads = count(), total_bytes = sum(bytes), avg_bytes = avg(bytes)
    by op, state, bin(TimeGenerated, 1h)
| order by TimeGenerated desc
```

- Before #89: `state == "fetched"`, `bytes > 0` (the embedding rode back on every read).
- After #89: `state == "deferred"`, `bytes == 0`.

The difference in `total_bytes` per op is the transfer #89 saves.

## Tear down

```
terraform destroy   # removes the test Container App + the Neon test branch
```
