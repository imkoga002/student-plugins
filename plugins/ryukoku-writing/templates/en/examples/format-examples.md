---
title: "Format samples (not content examples)"
---

<!-- Format samples only. Labels are placeholders such as "(claim)" or "Factor A" and contain no topic.
     Copy what you need into your manuscript and write the content yourself. Each Mermaid diagram pins
     theme, look and layout in front matter (Mermaid 12 changed the defaults: Mermaid, Flowchart syntax,
     "Default theme, look and layout (v12.0.0+)", https://mermaid.js.org/syntax/flowchart.html). -->

# Math (TeX) {#sec-math}

Inline math such as $\bar{x} = \frac{1}{n}\sum_{i=1}^{n} x_i$, and display math:

$$
\hat{\beta} = (X^{\top}X)^{-1}X^{\top}y
$$

$$
\begin{aligned}
y_i &= \beta_0 + \beta_1 x_i + \varepsilon_i \\
\varepsilon_i &\sim \mathcal{N}(0, \sigma^2)
\end{aligned}
$$

# Diagrams (Mermaid) {#sec-figures}

## Argument map (Toulmin layout)

```mermaid
---
config:
  theme: default
  look: classic
  layout: dagre
---
flowchart LR
  D["Data: (facts)"] --> W["Warrant: (general premise linking data to claim)"]
  B["Backing: (theory or prior work supporting the warrant)"] --> W
  W --> C(["Claim: (your claim)"])
  Q["Qualifier: (scope, strength)"] --> C
  R["Rebuttal: (conditions where the claim fails)"] -.-> C
```

## Causal diagram (hypothesised links dotted)

```mermaid
---
config:
  theme: default
  look: classic
  layout: dagre
---
flowchart LR
  A["Factor A"] --> M["Mediator M"]
  M --> Y["Outcome Y"]
  A -. "hypothesis: direct effect" .-> Y
  subgraph Possible confounders
    Z["Factor Z"]
  end
  Z --> A
  Z --> Y
```

## Research flow

```mermaid
---
config:
  theme: default
  look: classic
  layout: dagre
---
flowchart TD
  Q["Question (your RQ)"] --> L["Literature search"]
  L --> D["Data collection"]
  D --> A["Analysis"]
  A --> K["Discussion"]
  K -. "revise the question" .-> Q
```

## Timeline

```mermaid
---
config:
  theme: default
  look: classic
  layout: dagre
---
flowchart LR
  T1["20XX: (event 1)"] --> T2["20XX: (event 2)"] --> T3["20XX: (event 3)"]
```

## Concept map

```mermaid
---
config:
  theme: default
  look: classic
  layout: dagre
---
flowchart TB
  subgraph Upper["Broader concept (name)"]
    C1["Narrower concept 1"]
    C2["Narrower concept 2"]
  end
  C1 -- "relation" --> C2
  X["Related concept"] -.-> Upper
```

# Tables {#sec-tables}

| Item | Value | Source id |
|---|---:|---|
| (item 1) | (value) | S001 |
| (item 2) | (value) | S002 |

: Table 1 (caption; above or below the table as your guide requires) {#tbl-sample}

# Footnotes {#sec-notes}

Add a note where needed[^n1].

[^n1]: Note text. Whether sources go in notes or in the text depends on your citation style.

# Cross-references {#sec-xref}

Refer to sections like [the math section](#sec-math). Numbered references to figures/tables/equations
(@fig:...) need pandoc-crossref built for your pandoc version (pandoc-crossref README,
https://github.com/lierdakil/pandoc-crossref).

# Citations (sample, not processed)

```text
In-text: [@key, p. 12] / several: [@key1; @key2] / author in text: @key argues ...
key = the citekey or id in the ledger (sources/register.csv). The bibliography is built from the ledger at each export; only IDENTITY_CONFIRMED works appear.
```
