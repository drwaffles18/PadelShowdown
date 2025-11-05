# app.py — Padel Showdown (sin base de datos)
# Autor: Victor + GPT
# Descripción: App 100% en memoria para crear torneos de pádel (americano competitivo),
# registrar jugadores o equipos, generar rondas SIN byes (opcional), asignar canchas
# por ranking, registrar/editar resultados y ver leaderboard.
# v1.3 cambios: botón "Finalizar torneo" cuando se completan todas las rondas y resultados,
# vista de podio, conteo de rondas totales/generadas/restantes, fix del nombre por defecto
# incrementando Team # al agregar equipo (reseteo de widgets), y mejoras UX de bloqueo al finalizar.

# ============================================================
#  🎾 Padel Showdown — v1.5.7
# Autor: Victor + GPT
# Descripción:
# Torneos competitivos 2 vs 2 (americano competitivo) totalmente en memoria.
# Permite registrar jugadores, formar rondas automáticas, asignar canchas,
# registrar resultados, ver leaderboard y finalizar torneo.
# ============================================================



from __future__ import annotations
import json, random
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Tuple, Dict, Any
import pandas as pd
import streamlit as st
import re

st.set_page_config(page_title="Padel Showdown — sin BD", page_icon="🎾", layout="wide")

POINTS_WIN, POINTS_DRAW = 3, 1

# ==============================
# 🧱 Modelos
# ==============================
@dataclass
class Competidor:
    nombre: str
    miembros: Optional[Tuple[str, str]] = None
    puntos: int = 0; pg: int = 0; pe: int = 0; pp: int = 0; dif: int = 0; pj: int = 0
    def to_dict(self): return asdict(self)
    @staticmethod
    def from_dict(d): return Competidor(**d)

@dataclass
class Partido:
    comp1: List[str]; comp2: List[str]
    score1: Optional[int] = None; score2: Optional[int] = None
    jugado: bool = False; ronda: int = 1; cancha: Optional[str] = None
    def to_dict(self): return asdict(self)
    @staticmethod
    def from_dict(d): return Partido(**d)

# ==============================
# 🧮 Torneo
# ==============================
@dataclass
class Torneo:
    nombre: str; modo: str
    ronda_actual: int = 0
    competidores: Dict[str, Competidor] = field(default_factory=dict)
    partidos: List[Partido] = field(default_factory=list)
    canchas: List[str] = field(default_factory=list)
    permitir_byes: bool = False
    finalizado: bool = False

    def reset_all(self):
        for c in self.competidores.values():
            c.puntos = c.pg = c.pe = c.pp = c.dif = c.pj = 0
        self.partidos.clear()
        self.ronda_actual = 0
        self.finalizado = False

    def registrar_competidor(self, nombre: str, miembros: Optional[Tuple[str, str]] = None):
        if nombre in self.competidores: raise ValueError("Ya existe ese competidor.")
        self.competidores[nombre] = Competidor(nombre, miembros)

    def lista_comp(self): return list(self.competidores.keys())

    # ====== Leaderboard ======
    def leaderboard_df(self):
        df = pd.DataFrame([{
            "Nombre": c.nombre,
            "Equipo": f"{c.nombre}" if not c.miembros else f"{c.nombre} ({c.miembros[0]} / {c.miembros[1]})",
            "PTS": c.puntos, "PG": c.pg, "PE": c.pe, "PP": c.pp, "Dif": c.dif, "PJ": c.pj
        } for c in self.competidores.values()])
        if df.empty: return pd.DataFrame(columns=["Equipo","PTS","PG","PE","PP","Dif","PJ"])
        df = df.sort_values(by=["PTS","Dif","PG"], ascending=[False,False,False]).reset_index(drop=True)
        df.index += 1
        medals = ["🥇" if i==1 else ("🥈" if i==2 else ("🥉" if i==3 else "")) for i in df.index]
        df["Equipo"] = [f"{m} {n}".strip() for m,n in zip(medals,df["Equipo"])]
        return df[["Equipo","PTS","PG","PE","PP","Dif","PJ"]]

    # ====== Emparejamientos ======
    def total_rondas_posibles(self):
        n = len(self.competidores)
        if self.modo == "Individual":
            # Máximo teórico de rondas sin repetir compañero: n - 1 (para n par >= 4)
            return max(n - 1, 0) if n >= 4 and n % 2 == 0 else 0
        else:
            # Round-robin entre equipos (1 vs 1): n - 1
            return max(n - 1, 0)


    def generar_nueva_ronda(self):
        if self.finalizado:
            raise ValueError("El torneo ya fue finalizado.")

        total_max = self.total_rondas_posibles()
        if self.ronda_actual >= total_max:
            raise ValueError(f"Se alcanzó el máximo de rondas ({total_max}).")

        nombres = self.lista_comp()
        if len(nombres) < 4:
            raise ValueError("Se requieren al menos 4 jugadores/equipos para formar partidos.")

        self.ronda_actual += 1
        ronda = self.ronda_actual
        partidos: List[Partido] = []

        # =========================
        # MODO INDIVIDUAL (2v2)
        # =========================
        if self.modo == "Individual":
            # 🔹 1️⃣ RONDA INICIAL → aleatoria total
            if self.ronda_actual == 1:
                orden = nombres[:]
                random.shuffle(orden)
            # 🔹 2️⃣ RONDAS POSTERIORES → según ranking (PTS, DIF, PG)
            else:
                lb = self.leaderboard_df()
                if lb.empty:
                    orden = nombres[:]
                else:
                    orden = []
                    for fila in lb["Equipo"].tolist():
                        tokens = fila.strip().split(" ")
                        orden.append(tokens[-1])
                    orden = [n for n in orden if n in self.competidores] + [n for n in nombres if n not in orden]

            # Verifica paridad (para formar duplas)
            if len(orden) % 2 != 0:
                if not self.permitir_byes:
                    raise ValueError("Número impar de jugadores y 'Permitir byes' está desactivado.")
                orden = orden[:-1]

            # Forma duplas adyacentes por ranking: (1,2), (3,4), ...
            equipos = [orden[i:i+2] for i in range(0, len(orden), 2)]

            # Cada partido requiere 2 duplas → número de partidos
            num_matches = len(equipos) // 2

            # 🚫 Evitar canchas duplicadas dentro de la ronda
            if self.canchas and len(self.canchas) < num_matches:
                raise ValueError(f"Faltan canchas: se requieren {num_matches} canchas y definiste {len(self.canchas)}.")

            # Asignación por prioridad: match 1 → cancha 1, match 2 → cancha 2, etc.
            for m in range(num_matches):
                teamA = equipos[2*m]
                teamB = equipos[2*m + 1]
                cancha = self.canchas[m] if (self.canchas and m < len(self.canchas)) else None
                partidos.append(Partido(comp1=teamA, comp2=teamB, ronda=ronda, cancha=cancha))


        # =========================
        # MODO PAREJAS (equipo vs equipo)
        # =========================
        else:
            # Ordena por ranking actual de equipos
            orden_objs = sorted(self.competidores.values(), key=lambda c: (-c.puntos, -c.dif, -c.pg))
            order = [c.nombre for c in orden_objs]

            if len(order) % 2 != 0:
                if not self.permitir_byes:
                    raise ValueError("Número impar de equipos y 'Permitir byes' está desactivado.")
                order = order[:-1]

            num_matches = len(order) // 2

            # 🚫 Evitar canchas duplicadas dentro de la ronda
            if self.canchas and len(self.canchas) < num_matches:
                raise ValueError(f"Faltan canchas: se requieren {num_matches} canchas y definiste {len(self.canchas)}.")

            for m in range(num_matches):
                a = order[2*m]; b = order[2*m + 1]
                cancha = self.canchas[m] if (self.canchas and m < len(self.canchas)) else None
                partidos.append(Partido(comp1=[a], comp2=[b], ronda=ronda, cancha=cancha))

        self.partidos.extend(partidos)
        return partidos


    def partidos_de_ronda(self, ronda:int):
        return [p for p in self.partidos if p.ronda == ronda]

    def registrar_resultado(self, partido:Partido, score1:int, score2:int):
        partido.score1, partido.score2 = score1, score2
        partido.jugado = True
        # Recalcular puntos
        for c in self.competidores.values():
            c.puntos=c.pg=c.pe=c.pp=c.dif=c.pj=0

        for p in self.partidos:
            if not p.jugado: continue
            s1, s2 = int(p.score1), int(p.score2)
            if self.modo == "Individual":
                # Sumar a cada jugador de cada pareja
                for player in p.comp1+p.comp2:
                    if player not in self.competidores: continue
                    self.competidores[player].pj += 1
                for a in p.comp1:
                    for b in p.comp2:
                        self.competidores[a].dif += (s1 - s2)
                        self.competidores[b].dif += (s2 - s1)
                if s1 > s2:
                    for a in p.comp1:
                        self.competidores[a].pg += 1
                        self.competidores[a].puntos += POINTS_WIN
                    for b in p.comp2:
                        self.competidores[b].pp += 1
                elif s2 > s1:
                    for b in p.comp2:
                        self.competidores[b].pg += 1
                        self.competidores[b].puntos += POINTS_WIN
                    for a in p.comp1:
                        self.competidores[a].pp += 1
                else:
                    for player in p.comp1+p.comp2:
                        self.competidores[player].pe += 1
                        self.competidores[player].puntos += POINTS_DRAW
            else:
                c1 = self.competidores[p.comp1[0]]; c2 = self.competidores[p.comp2[0]]
                c1.pj += 1; c2.pj += 1; c1.dif += s1-s2; c2.dif += s2-s1
                if s1>s2: c1.pg+=1;c1.puntos+=POINTS_WIN;c2.pp+=1
                elif s2>s1: c2.pg+=1;c2.puntos+=POINTS_WIN;c1.pp+=1
                else: c1.pe+=1;c2.pe+=1;c1.puntos+=POINTS_DRAW;c2.puntos+=POINTS_DRAW

# ==============================
# 🖥️ UI
# ==============================
if "torneo" not in st.session_state: st.session_state.torneo=None
st.title("🎾 Padel Showdown — Torneos sin membresías (100% en memoria)")

# --- Sidebar ---
with st.sidebar:
    st.header("⚙️ Torneo")
    if st.session_state.torneo is None:
        nombre = st.text_input("Nombre del torneo", "Mi Torneo Padel Showdown")
        modo = st.radio("Modo", ["Individual", "Parejas"], horizontal=True)
        canchas = [c.strip() for c in re.split(r"[,.;\s]+", st.text_input("Canchas", "1,2,3")) if c.strip()]
        permitir_byes = st.checkbox("Permitir byes (solo Individual)", value=False)
        if st.button("🆕 Crear torneo", use_container_width=True):
            st.session_state.torneo = Torneo(nombre, modo, canchas=canchas, permitir_byes=permitir_byes)
            st.success("Torneo creado.")
    else:
        t = st.session_state.torneo
        st.subheader(f"{t.nombre} — {t.modo}")
        st.caption(f"Canchas: {', '.join(t.canchas)} — Finalizado: {'Sí' if t.finalizado else 'No'}")
        if st.button("🗑️ Reiniciar", use_container_width=True):
            t.reset_all(); st.info("Reiniciado."); st.rerun()

if st.session_state.torneo is None: st.stop()
t: Torneo = st.session_state.torneo

# --- Competidores ---
st.header("👥 Participantes")
if t.modo == "Individual":
    n = st.text_input("Nombre del jugador")
    if st.button("➕ Agregar jugador", use_container_width=True, disabled=t.finalizado):
        if not n.strip(): st.warning("Ingresa un nombre.")
        elif n in t.competidores: st.warning("Ya existe.")
        else: t.registrar_competidor(n.strip()); st.success(f"Jugador {n} agregado."); st.rerun()
else:
    if "_team_counter" not in st.session_state: st.session_state._team_counter = len(t.competidores)+1
    col1, col2 = st.columns(2)
    m1 = col1.text_input("Miembro 1"); m2 = col2.text_input("Miembro 2")
    if st.button("➕ Agregar equipo", use_container_width=True, disabled=t.finalizado):
        if not (m1.strip() and m2.strip()): st.warning("Completa ambos.")
        else:
            name = f"Team {st.session_state._team_counter}"
            t.registrar_competidor(name, (m1.strip(), m2.strip()))
            st.success(f"Equipo {name} agregado.")
            st.session_state._team_counter += 1; st.rerun()

if t.competidores:
    df = pd.DataFrame({"Competidor": list(t.competidores.keys())})
    st.dataframe(df, use_container_width=True)
else:
    st.info("Agrega competidores para continuar.")
st.divider()

# --- Rondas ---
st.header("🔁 Rondas")
total = t.total_rondas_posibles()
st.markdown(f"**Máximo de rondas:** {total} | **Generadas:** {t.ronda_actual}")
if not t.finalizado:
    if st.button("🆕 Generar nueva ronda", use_container_width=True):
        try:
            nuevos = t.generar_nueva_ronda()
            st.success(f"Ronda {t.ronda_actual} generada con {len(nuevos)} partido(s).")
        except Exception as e:
            st.error(str(e))
else:
    st.warning("🏁 Torneo finalizado. No se pueden generar más rondas.")

for r in range(1, t.ronda_actual + 1):
    ronda = t.partidos_de_ronda(r)
    with st.expander(f"Ronda {r} — {len(ronda)} partido(s)", expanded=(r == t.ronda_actual)):
        for idx, p in enumerate(ronda):
            cols = st.columns([2.8, 0.8, 0.8, 1])
            etiqueta = f"{' & '.join(p.comp1)} vs {' & '.join(p.comp2)}"
            if p.cancha: etiqueta += f" (Cancha {p.cancha})"
            cols[0].write(f"**{etiqueta}**")
            s1 = cols[1].number_input(" ", 0, 99, int(p.score1) if p.score1 else 0, key=f"s1_{r}_{idx}", disabled=t.finalizado)
            s2 = cols[2].number_input(" ", 0, 99, int(p.score2) if p.score2 else 0, key=f"s2_{r}_{idx}", disabled=t.finalizado)
            if cols[3].button("💾 Guardar", key=f"save_{r}_{idx}", disabled=t.finalizado):
                t.registrar_resultado(p, s1, s2)
                cols[3].success("✅ Guardado", icon="💾")


# --- Finalizar torneo ---
all_played = all(p.jugado for p in t.partidos) and t.partidos
if not t.finalizado and all_played:
    st.success("✅ Todas las rondas completas.")
    if st.button("🏁 Finalizar torneo", use_container_width=True):
        t.finalizado = True
        st.toast("🏁 ¡Torneo finalizado!", icon="🏆")
        st.rerun()

# --- Leaderboard ---
st.header("🏆 Leaderboard")
lb = t.leaderboard_df()
st.dataframe(lb, use_container_width=True)
if t.finalizado and len(lb) >= 3:
    st.markdown(
        f"🥇 **Campeón:** {lb.iloc[0]['Equipo']}  \n"
        f"🥈 **Subcampeón:** {lb.iloc[1]['Equipo']}  \n"
        f"🥉 **Tercer lugar:** {lb.iloc[2]['Equipo']}"
    )
