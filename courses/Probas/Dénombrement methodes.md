---
id: 04
title: "Dénombrement : Méthodes"
tags: [math, probas, dénombrement]
created: 2025-07-16
updated: 2025-07-16
---

# Méthodes

## Quels objets ?

Setup : Une urne avec 10 boules, on en tire 3.

### p-liste

Quand ? **Ordre + répétitions**.<br>

i.e : tirage successif avec remise $\Rightarrow$ $10^3$ possibilités.<br>

---
### p-liste d'éléments distincts ou arrangement

Quand ? **Ordre + pas de répétitions**.<br>
i.e : tirage successif sans remise $\Rightarrow$ $\frac{10!}{(10-3)!} = \frac{10!}{7!} = 10 \times 9 \times 8 = 720$ possibilités.<br>
---

### Permutation

Quand ? **Pas d'ordre + pas de répétitions + tous les éléments d'un ensemble**.<br>
i.e : tirage successif sans remise de toutes boules $\Rightarrow$ $10! = 3628800$ possibilités.<br>

_Note : C'est juste le cas particulier de l'arrangement où $p = n$ (tous les éléments)_.<br>

---
### Combinaison

Quand ? **Pas d'ordre + pas de répétitions**.<br>
i.e : tirage simultané sans remise $\Rightarrow$ $\binom{10}{3} = \frac{10!}{3!(10-3)!} = \frac{10!}{3!7!} = \frac{10 \times 9 \times 8}{3 \times 2 \times 1} = 120$ possibilités.<br>

---

## Quelles techniques ?

### Principe multiplicatif

Quand on a plusieurs étapes indépendantes, on multiplie le nombre de possibilités à chaque étape.<br>

$\Rightarrow$ Le mot-clé du raisonnement est le "_**et**_". (indépendance)<br>

ex : Combien de menus différents peut-on composer avec 3 entrées, 2 plats et 4 desserts ?<br>
Réponse : $3 \times 2 \times 4 = 24$ menus différents.<br>

ex : Combien de nombres à 5 chiffres sans 9 ?<br>
Réponse : $8 \times 9 \times 9 \times 9 \times 9$ nombres différents.<br> (le premier chiffre ne peut pas être 0 ni 9, les autres chiffres peuvent être 0 mais pas 9).<br>

### Passage au complémentaire

$\Rightarrow$ Le mot-clé du raisonnement est le "_**au moins un**_".<br>

En général, il est plus facile de compter le "aucun" et de le soustraire du total.<br>

ex : Combien de mots de 3 lettres avec au moins un "w" ?<br>
Réponse : $26^3 - 25^3 = 17576 - 15625 = 1951$ mots.<br> (26 lettres de l'alphabet, 25 sans "w").<br>

### Disjonction de cas

Quand on peut decomposer le problème en plusieurs cas mutuellement exclusifs.<br>

$\Rightarrow$ Le mot-clé du raisonnement est le "_**ou**_".<br>
Dans les faits, on transforme un "au moins" ou "au plus" en "exactement".<br>

ex : Au plus 2 $\Leftrightarrow$ exactement 0 ou exactement 1 ou exactement 2.<br>

ex : Combien de carrés dans une grille de 3x3 ?<br>
Réponse : Le carré peut être de taille 1 **ou** 2 **ou** 3 $\Rightarrow$ $3^2 + 2^2 + 1^2 = 9 + 4 + 1 = 14$ carrés.<br>

### Principe des tiroirs

Quand on a plus d'objets que de cas possibles, au moins un cas contient au moins deux objets.<br>
(Application de $\mathbb{E}$ à $\mathbb{F}$ ne peut pas être injective si $Card(\mathbb{E}) > Card(\mathbb{F})$).<br>

ex : Village de 700 habitants, peut-on trouver 2 personnes avec les mêmes initiales ?<br>
Réponse : Oui, car il y a 26 lettres pour le prénom et 26 pour le nom, donc $26 \times 26 = 676$ combinaisons possibles.<br>
(700 habitants > 676 combinaisons possibles $\Rightarrow$ au moins deux personnes ont les mêmes initiales).<br>

### Manipuler les coefficients binomiaux

- Par recurrence, en se servant de ce genre de formules $\binom{n}{p} = \binom{n-1}{p} + \binom{n-1}{p-1}$.
- En utilisant la formule du binôme : $(x+y)^n = \sum_{k=0}^{n} \binom{n}{k} x^k y^{n-k}$.
- En comptant de deux façons différentes et en égalant les deux expressions.<br>
ex : Formule de Pascal par dénombrement :<br>
Réponse : Il y a $\binom{n}{p}$ parties de cardinal $p$ dans un ensemble de cardinal $n$.<br> Mais si on considère un élément $x$ de l'ensemble de card $p$, il y a $\binom{n-1}{p-1}$ parties qui contiennent $x$ et $\binom{n-1}{p}$ parties qui ne le contiennent pas.<br>
Note : Ici on utilise aussi la disjonction de cas, on a trouvé une façon de "recouvrir" notre ensemble en 2 parties mutuellement exclusives.<br>

### Compter des ensembles

Un peu toutes les méthodes précédentes. En plus, on peut penser à faire un tableau à double entrée pour compter les éléments ou bien utiliser le *lemme du berger*, i. compter chaque élément $p$ fois et diviser le total par $p$<br>