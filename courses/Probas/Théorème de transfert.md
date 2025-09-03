---
id: 01
title: "Théorème de transfert"
tags: [math, probas, théorème ]
created: 2025-07-07
updated: 2025-07-07
---


Pour une variable aléatoire discrète $X$ à valeurs dans $\mathbb{N}$, le théorème de transfert est simplement l’égalité suivante :

$$\
\mathbb{E}(\varphi(X)) = \sum_{n \geq 0} \varphi(n) \ \mathbb{P}(X = n).
\$$

---
### 🎲 Exemple : espérance de $\frac{1}{X}$

Soit $X$ une variable aléatoire discrète prenant les valeurs \(1, 2, 3\) avec les probabilités suivantes :

- $\mathbb{P}(X = 1) = \frac{1}{2}$
- $\mathbb{P}(X = 2) = \frac{1}{3}$
- $\mathbb{P}(X = 3) = \frac{1}{6}$

**But :** calculer $\mathbb{E}\left( \frac{1}{X} \right)$

<details>
<summary>📐Application de la formule du transfert :</summary>

$$
\mathbb{E}\left( \frac{1}{X} \right) = \sum_{n=1}^{3} \frac{1}{n} \cdot \mathbb{P}(X = n)
= 1 \cdot \frac{1}{2} + \frac{1}{2} \cdot \frac{1}{3} + \frac{1}{3} \cdot \frac{1}{6}
= \frac{1}{2} + \frac{1}{6} + \frac{1}{18}
= \frac{13}{18}
$$
</details>