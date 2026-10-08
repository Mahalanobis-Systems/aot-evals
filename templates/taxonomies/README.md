# Vertical taxonomy templates

C2 starts the coverage list from `templates/taxonomies/<vertical>.yaml` when one fits the agent's
vertical. Each template has the same shape as `evals/taxonomy.yaml` and must name a real source
document written for some other purpose (a public API surface, a standard job-task taxonomy, a
regulator's list of duties). A template derived from anyone's eval cases is exactly what G5
exists to refuse, and a poor default becomes everyone's coverage list.

No vertical templates ship yet. Contributions are welcome: each needs a real, citable source
(see CONTRIBUTING.md). Until then C2 drafts the list from the team's own product spec, tool
surface or help-centre topics, and the owner edits it.

Template shape:

```yaml
name: <vertical> jobs
source:
  document: <title of the source document>
  kind: api-surface | job-taxonomy | regulation | help-centre | product-spec
  url: <where it is published>
read_on: <date>
template: templates/taxonomies/<vertical>.yaml
entries:
  - id: <stable-id>
    title: <short title>
    description: <one line, quoted or paraphrased from the source>
```
