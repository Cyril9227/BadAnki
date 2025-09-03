---
id: 02
title: "Dénombrement : Ensembles"
tags: [math, probas, dénombrement]
created: 2025-07-16
updated: 2025-07-16
---

## Rappel succinct

Soit $f : \mathbb{E} \to \mathbb{F}$ une application, où $\mathbb{E}$ et $\mathbb{F}$ sont des ensembles finis.

- Si $f$ est injective, alors $|\mathbb{E}| \leq |\mathbb{F}|$.
- Si $f$ est surjective, alors $|\mathbb{E}| \geq |\mathbb{F}|$.
- Si $f$ est bijective, alors $|\mathbb{E}| = |\mathbb{F}|$.

Si $\mathbb{E}$ et $\mathbb{F}$ sont finis et de même cardinal, alors on l'équivalence :

$f$ est injective $\iff$ $f$ est surjective $ \iff $ f est bijective.

---

Pour des ensembles finis $\mathbb{E_1}, \dots, \mathbb{E_n}$, le produit cartésien noté $\mathbb{E_1} \times \dots \times \mathbb{E_n}$ est un ensemble fini de cardinal :

$$
|\mathbb{E_1} \times \dots \times \mathbb{E_n}| = |\mathbb{E_1}| \cdot \dots \cdot |\mathbb{E_n}|
$$

---

$$
|\mathbb{E} \cup \mathbb{F}| = |\mathbb{E}| + |\mathbb{F}| - |\mathbb{E} \cap \mathbb{F}|
$$

*Naturellement, si $\mathbb{E}$ et $\mathbb{F}$ sont disjoints, alors* : $|\mathbb{E} \cup \mathbb{F}| = |\mathbb{E}| + |\mathbb{F}|$.

---

Pour $\mathbb{A_1}, \dots, \mathbb{A_n}$ des parties d'un ensemble $\mathbb{E}$, deux à deux disjointes dont la réunion est $\mathbb{E}$, on a :

$$
|\mathbb{E}| = |\mathbb{A_1}| + \dots + |\mathbb{A_n}|
$$

En particulier, si les $\mathbb{A_i}$ sont de même cardinal $p$, on a le *lemme des bergers* :

$$
|\mathbb{E}| = n \cdot |\mathbb{A_1}| = np
$$

*(En gros, au lieu de compter les moutons, on compte le nombre de pattes et on divise par 4...)*

---

L'ensemble $F$ des fonctions de $\mathbb{E}$ vers $\mathbb{F}$ est de cardinal :

$$
|F| = |\mathbb{F}|^{|\mathbb{E}|}
$$

L'ensemble $\mathcal{P}(\mathbb{E})$ des parties de $\mathbb{E}$ est de cardinal :

$$
|\mathcal{P}(\mathbb{E})| = 2^{|\mathbb{E}|}
$$
