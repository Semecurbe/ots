import numpy as np

x = np.asarray(data, dtype=np.float64)   # float64 : évite le débordement (S4 ≈ 1e5 counts → 1e15)
x = x - x.mean()                          # optionnel : retirer la composante continue (utile pour S4)
y = x ** 3                                # cube échantillon par échantillon, signe conservé

stats = {
    "mean_cube": float(y.mean()),
    "peak": float(np.max(np.abs(y))),
}
