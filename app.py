# app.py — Padel Showdown v1.4
# Autor: Victor + GPT
# Descripción: App 100% en memoria para torneos tipo Americano (Individual o Parejas),
# con rondas sin repetición, asignación de canchas, leaderboard y botón de finalización manual.

from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Tuple, Dict, Any
import random
import pandas as pd
import streamlit as st
from io import BytesIO

POINTS_WIN = 3
POINTS_DRAW = 1
POINTS_LOSS = 0

# ======================================
# 🧱 MODELOS
# ======================================

@dataclass
class Competidor:
    nombre: str
    miembros: Optional[Tuple[str, str]] = None
    puntos: int = 0
    pg: int = 0
    pe: int = 0
    pp: int = 0
    dif: int = 0
    pj: int = 0

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d):
        return Competidor(
            nombre=d["nombre"],
            miembros=tuple(d["miembros"]) if d.get("miembros") else None,
            puntos=d.get("puntos", 0),
            pg=d.get("pg", 0),
            pe=d.get("pe", 0),
            pp=d.get("pp", 0),
            dif=d.get("dif", 0),
            pj=d.get("pj", 0),
        )

@dataclass
class Partido:
    comp1: str
    comp2: str
    score1: Optional[int] = None
    score2: Optional[int] = None
    jugado: bool = False
    ronda: int = 1
    cancha: Optional[str] = None

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d):
        return Partido(**d)

# ======================================
# 🧩 LÓGICA DE TORNEO
# ======================================

@dataclass
class Torneo:
    nombre: str
    modo: str  # Individual o Parejas
    ronda_actual: int = 0
    competidores: Dict[str, Competidor] = field(default_factory=dict)
    partidos: List[Partido] = field(default_factory=list)
    canchas: List[str] = field(default_factory=list)
    permitir_byes: bool = False
    finalizado: bool = False

    def reset_stats_only(self):
        for c in self.competidores.values():
            c.puntos = c.pg = c.pe = c.pp = c.dif = c.pj = 0

    def reset_all_matches(self):
        self.reset_stats_only()
        for p in self.partidos:
            p.jugado = False
            p.score1 = p.score2 = None
            p.cancha = None
        self.ronda_actual = 0
        self.partidos = []
        self.finalizado = False

    def registrar_competidor(self, nombre, miembros=None):
        if nombre in self.competidores:
            raise ValueError("Ya existe un competidor con ese nombre.")
        self.competidores[nombre] = Competidor(nombre=nombre, miembros=miembros)

    def lista_comp(self):
        return list(self.competidores.keys())

    def display_name(self, c):
        if self.modo == "Parejas" and c.miembros:
            return f"{c.nombre} ({c.miembros[0]} / {c.miembros[1]})"
        return c.nombre

    def leaderboard_base(self):
        rows = []
        for c in self.competidores.values():
            rows.append({
                "Nombre": c.nombre,
                "EquipoDisplay": self.display_name(c),
                "PTS": c.puntos,
                "PG": c.pg,
                "PE": c.pe,
                "PP": c.pp,
                "Dif": c.dif,
                "PJ": c.pj,
            })
        return pd.DataFrame(rows)

    def leaderboard_df(self):
        df = self.leaderboard_base()
        if df.empty:
            return pd.DataFrame(columns=["Equipo", "PTS", "PG", "PE", "PP", "Dif", "PJ"])
        if df["PTS"].sum() == 0:
            df = df.sort_values(by=["EquipoDisplay"])
        else:
            df = df.sort_values(by=["PTS", "Dif", "PG", "EquipoDisplay"], ascending=[False, False, False, True])
        df = df.reset_index(drop=True)
        df.index = df.index + 1
        med = ["🥇" if i==1 else ("🥈" if i==2 else ("🥉" if i==3 else "")) for i in df.index]
        df["Equipo"] = [f"{m} {n}".strip() for m, n in zip(med, df["EquipoDisplay"])]
        return df[["Equipo", "PTS", "PG", "PE", "PP", "Dif", "PJ"]]

    def total_rondas_posibles(self):
        n = len(self.competidores)
        return max(n - 1, 0) if n > 1 else 0

    # ------------------------
    # 🎾 GENERAR RONDAS
    # ------------------------
    def generar_nueva_ronda(self):
        if self.finalizado:
            raise ValueError("El torneo ya fue finalizado.")
        nombres = self.lista_comp()
        n = len(nombres)
        if n < 2:
            raise ValueError("Se requieren al menos 2 competidores.")
        if n % 2 == 1 and not self.permitir_byes:
            raise ValueError("Número impar de competidores sin permitir byes.")

        self.ronda_actual += 1
        ronda = self.ronda_actual

        # --- PAREJAS ---
        if self.modo == "Parejas":
            base = self.leaderboard_base()
            base = base.sort_values(by=["PTS", "Dif", "PG"], ascending=[False, False, False])
            order = list(base["Nombre"].values)
            pairs = [(order[i], order[i+1]) for i in range(0, len(order)-1, 2)]
            partidos = []
            for idx, (a, b) in enumerate(pairs):
                cancha = self.canchas[idx % len(self.canchas)] if self.canchas else None
                partidos.append(Partido(comp1=a, comp2=b, ronda=ronda, cancha=cancha))
            self.partidos.extend(partidos)
            return partidos

        # --- INDIVIDUAL AMERICANO ---
        base = self.leaderboard_base()
        base = base.sort_values(by=["PTS", "Dif", "PG"], ascending=[False, False, False])
        jugadores = list(base["Nombre"].values)
        random.shuffle(jugadores)

        prev_pairs = {(min(p.comp1, p.comp2), max(p.comp1, p.comp2)) for p in self.partidos}
        partidos = []
        i = 0
        while i + 3 < len(jugadores):
            grupo = jugadores[i:i+4]
            random.shuffle(grupo)
            j1, j2, j3, j4 = grupo

            posibles = [
                ((j1, j2), (j3, j4)),
                ((j1, j3), (j2, j4)),
                ((j1, j4), (j2, j3))
            ]
            for pareja1, pareja2 in posibles:
                if ((min(pareja1), max(pareja1)) not in prev_pairs and
                    (min(pareja2), max(pareja2)) not in prev_pairs):
                    cancha = self.canchas[len(partidos) % len(self.canchas)] if self.canchas else None
                    partidos.append(Partido(
                        comp1=f"{pareja1[0]}-{pareja1[1]}",
                        comp2=f"{pareja2[0]}-{pareja2[1]}",
                        ronda=ronda,
                        cancha=cancha
                    ))
                    prev_pairs.add((min(pareja1), max(pareja1)))
                    prev_pairs.add((min(pareja2), max(pareja2)))
                    break
            i += 4

        if not partidos:
            raise ValueError("No se pudieron generar nuevos emparejamientos sin repetir.")
        self.partidos.extend(partidos)
        return partidos

    def registrar_resultado(self, partido, score1, score2):
        partido.score1 = score1
        partido.score2 = score2
        partido.jugado = True
        self.recompute_all_stats()

    def recompute_all_stats(self):
        self.reset_stats_only()
        for p in self.partidos:
            if not p.jugado:
                continue
            c1 = self.competidores.get(p.comp1)
            c2 = self.competidores.get(p.comp2)
            if not c1 or not c2:
                continue
            s1, s2 = int(p.score1), int(p.score2)
            c1.pj += 1; c2.pj += 1
            c1.dif += s1 - s2; c2.dif += s2 - s1
            if s1 > s2:
                c1.pg += 1; c1.puntos += POINTS_WIN; c2.pp += 1
            elif s2 > s1:
                c2.pg += 1; c2.puntos += POINTS_WIN; c1.pp += 1
            else:
                c1.pe += 1; c2.pe += 1
                c1.puntos += POINTS_DRAW; c2.puntos += POINTS_DRAW

# ======================================
# 🖥️ INTERFAZ STREAMLIT
# ======================================

st.set_page_config(page_title="Padel Showdown", page_icon="🎾", layout="wide")

if "torneo" not in st.session_state:
    st.session_state.torneo = None

st.title("🎾 Padel Showdown — Torneos sin membresías")

# === SIDEBAR ===
with st.sidebar:
    st.header("⚙️ Torneo")
    if st.session_state.torneo is None:
        nombre = st.text_input("Nombre del torneo", "Mi Torneo Padel Showdown")
        modo = st.radio("Modo", ["Individual", "Parejas"], horizontal=True)
        canchas_text = st.text_input("Canchas (separadas por coma)", "3,4,5")
        permitir_byes = st.checkbox("Permitir byes (si cantidad impar)", False)
        if st.button("🆕 Crear torneo", use_container_width=True):
            canchas = [c.strip() for c in canchas_text.split(",") if c.strip()]
            st.session_state.torneo = Torneo(nombre, modo, canchas=canchas, permitir_byes=permitir_byes)
            st.success("Torneo creado.")
    else:
        t = st.session_state.torneo
        st.subheader(f"🏷️ {t.nombre} — {t.modo}")
        st.caption(f"Canchas: {', '.join(t.canchas)} | Finalizado: {'Sí' if t.finalizado else 'No'}")

        def _excel_bytes():
            lb = t.leaderboard_df()
            partidos_df = pd.DataFrame([p.to_dict() for p in t.partidos])
            bio = BytesIO()
            with pd.ExcelWriter(bio, engine="xlsxwriter") as writer:
                lb.to_excel(writer, "Leaderboard", index=True)
                partidos_df.to_excel(writer, "Partidos", index=False)
            bio.seek(0)
            return bio

        st.download_button(
            "💾 Descargar Excel",
            data=_excel_bytes(),
            file_name="padel_showdown.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

# === CUERPO ===
if st.session_state.torneo is None:
    st.info("Crea o carga un torneo para comenzar.")
    st.stop()

t: Torneo = st.session_state.torneo

# 👥 Competidores
st.header("👥 Competidores")
if t.modo == "Individual":
    nombre = st.text_input("Nombre del jugador", key="jugador")
    if st.button("➕ Agregar jugador", use_container_width=True, disabled=t.finalizado):
        if not nombre.strip():
            st.warning("Ingresa un nombre válido.")
        elif nombre.strip() in t.competidores:
            st.warning("Ya existe ese jugador.")
        else:
            t.registrar_competidor(nombre.strip())
            st.success(f"Jugador {nombre} agregado.")
else:
    j1 = st.text_input("Miembro 1", key="p1")
    j2 = st.text_input("Miembro 2", key="p2")
    if st.button("➕ Agregar equipo", use_container_width=True, disabled=t.finalizado):
        nombre_equipo = f"Team {len(t.competidores)+1}"
        t.registrar_competidor(nombre_equipo, (j1.strip(), j2.strip()))
        st.success(f"Equipo {nombre_equipo} agregado.")

# Ver competidores
if t.competidores:
    df = pd.DataFrame([
        {"Equipo": c.nombre, "Miembro 1": c.miembros[0] if c.miembros else "-", "Miembro 2": c.miembros[1] if c.miembros else "-"}
        for c in t.competidores.values()
    ])
    st.dataframe(df, use_container_width=True)
else:
    st.info("Agrega competidores antes de continuar.")

# 🔁 Rondas
st.header("🔁 Rondas")
colr1, colr2 = st.columns([1,3])
with colr1:
    gen = st.button("🆕 Generar nueva ronda", use_container_width=True, disabled=t.finalizado)
    if gen:
        try:
            nuevos = t.generar_nueva_ronda()
            st.success(f"Ronda {t.ronda_actual} generada con {len(nuevos)} partidos.")
        except Exception as e:
            st.error(str(e))
with colr2:
    st.write(f"**Rondas generadas:** {t.ronda_actual}")

# Mostrar rondas
if t.ronda_actual > 0:
    for r in range(1, t.ronda_actual+1):
        partidos_r = [p for p in t.partidos if p.ronda == r]
        with st.expander(f"Ronda {r}", expanded=(r==t.ronda_actual)):
            for idx, p in enumerate(partidos_r):
                cols = st.columns([3,1,1,1])
                with cols[0]:
                    label = f"{p.comp1} vs {p.comp2}"
                    if p.cancha:
                        label += f" (Cancha {p.cancha})"
                    st.write(f"**{label}**")
                with cols[1]:
                    s1 = st.number_input(f"Score {p.comp1}", 0, 100, value=p.score1 or 0, key=f"s1_{r}_{idx}", disabled=t.finalizado)
                with cols[2]:
                    s2 = st.number_input(f"Score {p.comp2}", 0, 100, value=p.score2 or 0, key=f"s2_{r}_{idx}", disabled=t.finalizado)
                with cols[3]:
                    if st.button("💾 Guardar", key=f"save_{r}_{idx}", disabled=t.finalizado):
                        t.registrar_resultado(p, int(s1), int(s2))
                        st.success("Resultado guardado.")

# 🏁 Finalizar torneo manualmente
if not t.finalizado:
    with st.expander("🏁 Finalizar torneo manualmente"):
        st.warning("Una vez finalizado, no podrás editar ni generar nuevas rondas.")
        if st.button("✅ Confirmar y finalizar torneo", use_container_width=True):
            t.finalizado = True
            st.success("🏁 ¡Torneo finalizado manualmente!")
            st.toast("¡Torneo finalizado!", icon="🏁")

# 🏆 Leaderboard
st.header("🏆 Leaderboard")
df = t.leaderboard_df()
st.dataframe(df, use_container_width=True)
if t.finalizado and not df.empty and len(df) >= 3:
    st.markdown(
        f"""
        🥇 **Campeón:** {df.iloc[0]['Equipo']}  
        🥈 **Subcampeón:** {df.iloc[1]['Equipo']}  
        🥉 **Tercer lugar:** {df.iloc[2]['Equipo']}
        """
    )
