---
id: 03
title: "Dénombrement : Objets"
tags: [math, probas, dénombrement]
created: 2025-07-16
updated: 2025-07-16
---

## Objets 

### p-liste

C'est une liste python... $[a_1, a_2, \ldots, a_p]$.<br>
<i>Remarque : L'ordre compte et il peut y avoir des répétitions.</i>

Nombre de p-listes de $\mathbb{E}$ (de cardinal $n$) : $n^p$.

---
### p-liste d'éléments distincts ou arrangement

Nombre de p-listes d'éléments distincts de $\mathbb{E}$ :  $\frac{n!}{(n-p)!}$.<br>
<i>Remarque : C'est aussi le <u>nombre d'injections</u> d'un ensemble de cardinal $p$ dans un ensemble de cardinal $n$.</i>

---
### Permutation

C'est une bijection de $\mathbb{E}$ dans $\mathbb{E}$ et il y en a $n!$.

---
### Combinaison

C'est un sous-ensemble de $\mathbb{E}$ de cardinal $p$, il y en a $\binom{n}{p} = \frac{n!}{p!(n-p)!}$.

---
### Coefficients binomiaux et calculs
- $\binom{n}{p} = \frac{n!}{p!(n-p)!}$.
- $\binom{n}{p} = \binom{n}{n-p}$.
- $\binom{n}{p} = \binom{n-1}{p} + \binom{n-1}{p-1}$ (formule de Pascal).
- $\binom{n}{p} = \frac{n}{p} \binom{n-1}{p-1}$.
- Formule du binôme : $(x+y)^n = \sum_{k=0}^{n} \binom{n}{k} x^k y^{n-k}$.
  - En particulier, pour $x=1$ et $y=1$, on a : $\sum_{k=0}^{n} \binom{n}{k} = 2^n$.
