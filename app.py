# app.py — Padel Showdown (sin base de datos)
# Autor: Victor + GPT
# Descripción: App 100% en memoria para crear torneos de pádel (americano competitivo),
# registrar jugadores o equipos, generar rondas SIN byes (opcional), asignar canchas
# por ranking, registrar/editar resultados y ver leaderboard.
# v1.3 cambios: botón "Finalizar torneo" cuando se completan todas las rondas y resultados,
# vista de podio, conteo de rondas totales/generadas/restantes, fix del nombre por defecto
# incrementando Team # al agregar equipo (reseteo de widgets), y mejoras UX de bloqueo al finalizar.

from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Tuple, Dict, Any
import random
import pandas as pd
import streamlit as st
from io import BytesIO

# ==============================
# 🧱 Modelos en memoria
# ==============================

POINTS_WIN = 3
POINTS_DRAW = 1
POINTS_LOSS = 0

@dataclass
class Competidor:
    nombre: str
    miembros: Optional[Tuple[str, str]] = None  # sólo en modo Parejas
    puntos: int = 0
    pg: int = 0
    pe: int = 0
    pp: int = 0
    dif: int = 0  # diferencia (a favor − en contra)
    pj: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Competidor":
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

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Partido":
        return Partido(
            comp1=d["comp1"], comp2=d["comp2"], score1=d.get("score1"), score2=d.get("score2"),
            jugado=d.get("jugado", False), ronda=d.get("ronda", 1), cancha=d.get("cancha")
        )

@dataclass
class Torneo:
    nombre: str
    modo: str  # "Individual" | "Parejas"
    ronda_actual: int = 0
    competidores: Dict[str, Competidor] = field(default_factory=dict)
    partidos: List[Partido] = field(default_factory=list)
    canchas: List[str] = field(default_factory=list)
    permitir_byes: bool = False
    finalizado: bool = False

    # ======= utilidades =======
    def reset_stats_only(self):
        for c in self.competidores.values():
            c.puntos = c.pg = c.pe = c.pp = c.dif = c.pj = 0

    def reset_all_matches(self):
        self.reset_stats_only()
        for p in self.partidos:
            p.jugado = False
            p.score1 = None
            p.score2 = None
            p.cancha = None
        self.ronda_actual = 0
        self.partidos = []
        self.finalizado = False

    def registrar_competidor(self, nombre: str, miembros: Optional[Tuple[str, str]] = None):
        if nombre in self.competidores:
            raise ValueError("Ya existe un competidor con ese nombre.")
        self.competidores[nombre] = Competidor(nombre=nombre, miembros=members if (members := miembros) else None)

    def lista_comp(self) -> List[str]:
        return list(self.competidores.keys())

    def display_name(self, c: Competidor) -> str:
        if self.modo == "Parejas" and c.miembros:
            return f"{c.nombre} ({c.miembros[0]} / {c.miembros[1]})"
        return c.nombre

    def leaderboard_base(self) -> pd.DataFrame:
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

    def leaderboard_df(self) -> pd.DataFrame:
        df = self.leaderboard_base()
        if df.empty:
            return pd.DataFrame(columns=["#", "Equipo", "PTS", "PG", "PE", "PP", "Dif", "PJ"])  # vacío
        if df["PTS"].sum() == 0:
            df = df.sort_values(by=["EquipoDisplay"], ascending=True)
        else:
            df = df.sort_values(by=["PTS", "Dif", "PG", "EquipoDisplay"], ascending=[False, False, False, True])
        df = df.reset_index(drop=True)
        df.index = df.index + 1
        df.index.name = "#"
        med = ["🥇" if i==1 else ("🥈" if i==2 else ("🥉" if i==3 else "")) for i in df.index]
        df["Equipo"] = [f"{m} {n}".strip() for m, n in zip(med, df["EquipoDisplay"]) ]
        return df[["Equipo", "PTS", "PG", "PE", "PP", "Dif", "PJ"]]

    def partidos_de_ronda(self, ronda: int) -> List[Partido]:
        return [p for p in self.partidos if p.ronda == ronda]

    # ======= lógica de rondas =======
    def total_rondas_posibles(self) -> int:
        n = len(self.competidores)
        return max(n - 1, 0) if n > 1 else 0

    def _pairings_round1(self, nombres: List[str]) -> List[tuple[str, str]]:
        n = len(nombres)
        if n % 2 == 1 and not self.permitir_byes:
            raise ValueError("Número impar de competidores y 'Permitir byes' está desactivado.")
        pool = nombres[:]
        random.shuffle(pool)
        return [(pool[i], pool[i+1]) for i in range(0, len(pool)-1, 2)]

    def _pairings_competitive(self) -> List[tuple[str, str]]:
        base = self.leaderboard_base()
        base = base.sort_values(by=["PTS", "Dif", "PG", "EquipoDisplay"], ascending=[False, False, False, True])
        order = list(base["Nombre"].values)
        n = len(order)
        if n % 2 == 1 and not self.permitir_byes:
            raise ValueError("Número impar de competidores y 'Permitir byes' está desactivado.")
        return [(order[i], order[i+1]) for i in range(0, len(order)-1, 2)]

    def generar_nueva_ronda(self):
        if self.finalizado:
            raise ValueError("El torneo ya fue finalizado.")
        nombres = self.lista_comp()
        n = len(nombres)
        if n < 2:
            raise ValueError("Se requieren al menos 2 competidores para generar una ronda.")
        if n % 2 == 1 and not self.permitir_byes:
            raise ValueError("Cantidad impar de competidores. Activa 'Permitir byes' o ajusta los competidores.")

        self.ronda_actual += 1
        ronda = self.ronda_actual
        pairs = self._pairings_round1(nombres) if ronda == 1 else self._pairings_competitive()

        # Asignar canchas por prioridad (si faltan canchas, se ciclan)
        partidos = []
        for idx, (a, b) in enumerate(pairs):
            cancha = None
            if self.canchas:
                cancha = self.canchas[idx % len(self.canchas)]
            partidos.append(Partido(comp1=a, comp2=b, ronda=ronda, cancha=cancha))

        self.partidos.extend(partidos)
        return partidos

    def registrar_resultado(self, partido: Partido, score1: int, score2: int):
        partido.score1 = score1
        partido.score2 = score2
        partido.jugado = True
        self.recompute_all_stats()

    def recompute_all_stats(self):
        self.reset_stats_only()
        for p in self.partidos:
            if not p.jugado:
                continue
            c1 = self.competidores[p.comp1]
            c2 = self.competidores[p.comp2]
            s1 = int(p.score1)
            s2 = int(p.score2)
            c1.pj += 1
            c2.pj += 1
            c1.dif += (s1 - s2)
            c2.dif += (s2 - s1)
            if s1 > s2:
                c1.pg += 1
                c1.puntos += POINTS_WIN
                c2.pp += 1
            elif s2 > s1:
                c2.pg += 1
                c2.puntos += POINTS_WIN
                c1.pp += 1
            else:
                c1.pe += 1
                c2.pe += 1
                c1.puntos += POINTS_DRAW
                c2.puntos += POINTS_DRAW

    # ======= serialización =======
    def to_json(self) -> str:
        d = {
            "nombre": self.nombre,
            "modo": self.modo,
            "ronda_actual": self.ronda_actual,
            "competidores": {k: v.to_dict() for k, v in self.competidores.items()},
            "partidos": [p.to_dict() for p in self.partidos],
            "canchas": self.canchas,
            "permitir_byes": self.permitir_byes,
            "finalizado": self.finalizado,
        }
        return json.dumps(d, ensure_ascii=False, indent=2)

    @staticmethod
    def from_json(s: str) -> "Torneo":
        d = json.loads(s)
        t = Torneo(
            nombre=d["nombre"],
            modo=d["modo"],
            ronda_actual=d.get("ronda_actual", 0),
            canchas=d.get("canchas", []),
            permitir_byes=d.get("permitir_byes", False),
            finalizado=d.get("finalizado", False),
        )
        t.competidores = {k: Competidor.from_dict(v) for k, v in d.get("competidores", {}).items()}
        t.partidos = [Partido.from_dict(p) for p in d.get("partidos", [])]
        t.recompute_all_stats()
        return t

# ==============================
# 🖥️ UI Streamlit
# ==============================
st.set_page_config(page_title="Padel Showdown — sin BD", page_icon="🎾", layout="wide")

# Estado global en sesión
if "torneo" not in st.session_state:
    st.session_state.torneo: Optional[Torneo] = None

st.title("🎾 Padel Showdown — Torneos sin membresías (100% en memoria)")

# --- Sidebar: Crear / Cargar / Guardar ---
with st.sidebar:
    st.header("⚙️ Torneo")
    if st.session_state.torneo is None:
        nombre = st.text_input("Nombre del torneo", value="Mi Torneo Padel Showdown")
        modo = st.radio("Modo", options=["Individual", "Parejas"], horizontal=True)
        canchas_text = st.text_input("Canchas (separadas por coma)", value="")
        permitir_byes = st.checkbox("Permitir byes (si cantidad impar)", value=False)
        if st.button("🆕 Crear torneo", use_container_width=True):
            canchas = [c.strip() for c in canchas_text.split(',') if c.strip()]
            st.session_state.torneo = Torneo(
                nombre=nombre.strip() or "Torneo",
                modo=modo,
                canchas=canchas,
                permitir_byes=permitir_byes,
            )
            st.success("Torneo creado.")
    else:
        t = st.session_state.torneo
        st.subheader(f"🏷️ {t.nombre} — {t.modo}")
        st.caption(f"Canchas: {', '.join(t.canchas) if t.canchas else 'Sin asignar'} — Permitir byes: {'Sí' if t.permitir_byes else 'No'} — Finalizado: {'Sí' if t.finalizado else 'No'}")

        # Exportar a Excel (Leaderboard + Partidos)
        def _excel_bytes():
            lb = t.leaderboard_df()
            partidos_df = pd.DataFrame([
                {
                    "Ronda": p.ronda,
                    "Equipo 1": t.competidores[p.comp1].nombre,
                    "Equipo 2": t.competidores[p.comp2].nombre,
                    "Cancha": p.cancha,
                    "Score 1": p.score1,
                    "Score 2": p.score2,
                    "Jugado": p.jugado,
                }
                for p in t.partidos
            ])
            bio = BytesIO()
            with pd.ExcelWriter(bio, engine="xlsxwriter") as writer:
                lb.to_excel(writer, sheet_name="Leaderboard", index=True)
                partidos_df.to_excel(writer, sheet_name="Partidos", index=False)
            bio.seek(0)
            return bio

        st.download_button(
            label="💾 Descargar Excel (Leaderboard + Partidos)",
            data=_excel_bytes(),
            file_name="padel_showdown.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

        st.divider()
        col_reset1, col_reset2 = st.columns(2)
        with col_reset1:
            if st.button("🔁 Recalcular estadísticas", use_container_width=True):
                t.recompute_all_stats()
                st.success("Estadísticas recalculadas.")
        with col_reset2:
            if st.button("🗑️ Reiniciar TODO (mantener competidores)", use_container_width=True):
                t.reset_all_matches()
                st.info("Se reiniciaron rondas y resultados. Competidores conservados.")

        with st.expander("Importar desde JSON (opcional)"):
            up = st.file_uploader("Cargar JSON", type=["json"], accept_multiple_files=False)
            if up is not None:
                try:
                    data = up.read().decode("utf-8")
                    st.session_state.torneo = Torneo.from_json(data)
                    st.success("Torneo cargado correctamente.")
                except Exception as e:
                    st.error(f"Error al cargar JSON: {e}")

# --- Main content ---
if st.session_state.torneo is None:
    st.info("Crea o carga un torneo desde la barra lateral para comenzar.")
    st.stop()

t: Torneo = st.session_state.torneo

# ==============================
# 👥 Competidores
# ==============================
st.header("👥 Competidores")

if t.modo == "Individual":
    c1, c2 = st.columns([2, 1])
    with c1:
        nombre = st.text_input("Nombre del jugador", key="add_player")
    with c2:
        disabled = t.finalizado
        if st.button("➕ Agregar jugador", use_container_width=True, disabled=disabled):
            if t.finalizado:
                st.warning("El torneo está finalizado. No se pueden agregar jugadores.")
            elif not nombre.strip():
                st.warning("Ingresa un nombre válido.")
            elif nombre.strip() in t.competidores:
                st.warning("Ese nombre ya existe.")
            else:
                t.registrar_competidor(nombre.strip())
                st.success(f"Jugador '{nombre.strip()}' agregado.")

else:  # Parejas
    with st.expander("Registrar equipo (pareja)", expanded=True):
        # Contador de equipos
        if "_team_counter" not in st.session_state:
            st.session_state._team_counter = len(t.competidores) + 1

        col1, col2 = st.columns([1.5, 1.5])
        with col1:
            j1 = st.text_input("Miembro 1", key="pair_m1")
        with col2:
            j2 = st.text_input("Miembro 2", key="pair_m2")

        add_team = st.button("➕ Agregar equipo", use_container_width=True, disabled=t.finalizado)
        if add_team:
            if t.finalizado:
                st.warning("El torneo está finalizado. No se pueden agregar equipos.")
            elif not (j1.strip() and j2.strip()):
                st.warning("Completa Miembro 1 y Miembro 2.")
            else:
                # Generar nombre automático
                nombre_equipo = f"Team {st.session_state._team_counter}"

                if nombre_equipo in t.competidores:
                    st.warning("Ya existe un equipo con ese nombre.")
                else:
                    t.registrar_competidor(nombre_equipo, (j1.strip(), j2.strip()))
                    st.success(f"✅ Equipo '{nombre_equipo}' agregado ({j1.strip()} / {j2.strip()})")

                    # Incrementar contador y forzar refresco
                    st.session_state._team_counter += 1
                    st.rerun()





if t.competidores:
    with st.expander("Ver competidores", expanded=True):
        if t.modo == "Individual":
            dfp = pd.DataFrame({"Jugador": [t.display_name(c) for c in t.competidores.values()]})
            st.dataframe(dfp, use_container_width=True)
        else:
            df_teams = pd.DataFrame([
                {"Equipo": c.nombre, "Miembro 1": c.miembros[0], "Miembro 2": c.miembros[1]}
                for c in t.competidores.values() if c.miembros is not None
            ]).sort_values(by=["Equipo"]).reset_index(drop=True)
            st.dataframe(df_teams, use_container_width=True)
else:
    st.info("Agrega competidores para poder generar rondas.")

st.divider()

# ==============================
# 🔁 Rondas y emparejamientos
# ==============================
st.header("🔁 Rondas")

# Mostrar conteo de rondas
total_rondas = t.total_rondas_posibles()
rondas_restantes = max(total_rondas - t.ronda_actual, 0)
st.markdown(
    f"**Rondas totales posibles:** {total_rondas}  |  **Generadas:** {t.ronda_actual}  |  **Restantes:** {rondas_restantes}"
)

colr1, colr2 = st.columns([1, 3])
with colr1:
    gen_disabled = t.finalizado
    gen = st.button("🆕 Generar nueva ronda", use_container_width=True, disabled=gen_disabled)
    if gen:
        try:
            nuevos = t.generar_nueva_ronda()
            st.success(f"Ronda {t.ronda_actual} generada con {len(nuevos)} partido(s).")
        except Exception as e:
            st.error(str(e))

with colr2:
    if t.ronda_actual > 0:
        st.write(f"**Ronda actual:** {t.ronda_actual}")
    else:
        st.write("Aún no hay rondas generadas.")

# Listado de rondas (bloquea edición si finalizado)
if t.ronda_actual > 0:
    for r in range(1, t.ronda_actual + 1):
        partidos_r = t.partidos_de_ronda(r)
        with st.expander(f"Ronda {r} — {len(partidos_r)} partido(s)", expanded=(r == t.ronda_actual)):
            if not partidos_r:
                st.write("(sin partidos)")
            else:
                for idx, p in enumerate(partidos_r):
                    cols = st.columns([3, 1, 1, 1])
                    with cols[0]:
                        etiqueta = f"{t.competidores[p.comp1].nombre} vs {t.competidores[p.comp2].nombre}"
                        if p.cancha is not None:
                            etiqueta += f"  (Cancha {p.cancha})"
                        st.write(f"**{etiqueta}**")
                    with cols[1]:
                        s1 = st.number_input(
                            f"Score {p.comp1}", min_value=0, value=int(p.score1) if p.score1 is not None else 0,
                            key=f"s1_{r}_{idx}", disabled=t.finalizado
                        )
                    with cols[2]:
                        s2 = st.number_input(
                            f"Score {p.comp2}", min_value=0, value=int(p.score2) if p.score2 is not None else 0,
                            key=f"s2_{r}_{idx}", disabled=t.finalizado
                        )
                    with cols[3]:
                        if st.button("💾 Guardar / Actualizar", key=f"save_{r}_{idx}", disabled=t.finalizado):
                            t.registrar_resultado(p, int(s1), int(s2))
                            st.success("Resultado guardado y leaderboard recalculado.")

# Mostrar botón "Finalizar torneo" cuando se cumpla condición
all_played = (t.ronda_actual >= total_rondas) and all(p.jugado for p in t.partidos) and total_rondas > 0
if not t.finalizado and all_played:
    st.success("✅ Todas las rondas y resultados están completos.")
    if st.button("🏁 Finalizar torneo", use_container_width=True):
        t.finalizado = True
        st.toast("¡Torneo finalizado!", icon="🏁")

st.divider()

# ==============================
# 🏆 Leaderboard / Resultados finales
# ==============================
if t.finalizado:
    st.subheader("🏆 Torneo Finalizado — Podio")
    df = t.leaderboard_df()
    st.dataframe(df, use_container_width=True)
    if not df.empty and len(df) >= 3:
        top3 = df.head(3)
        st.markdown(
            f"""
            🥇 **Campeón:** {top3.iloc[0]['Equipo']}  
            🥈 **Subcampeón:** {top3.iloc[1]['Equipo']}  
            🥉 **Tercer lugar:** {top3.iloc[2]['Equipo']}
            """
        )
else:
    st.header("🏆 Leaderboard (vivo)")
    df = t.leaderboard_df()
    st.dataframe(df, use_container_width=True)

# ==============================
# ℹ️ Notas
# ==============================
with st.expander("ℹ️ Notas y próximos pasos"):
    st.markdown(
        """
        - **Formato competitivo**: R1 aleatoria; desde R2 emparejamiento por ranking (1vs2, 3vs4...).
        - **Canchas**: se asignan en el orden ingresado (p.ej., "3,4,5"). El partido de mayor ranking va a la primera.
        - **Byes**: si está desactivado y la cantidad es impar, se pedirá ajustar competidores.
        - **Editar resultados**: puedes cambiar scores en cualquier ronda; el leaderboard se recalcula completo. Tras **finalizar**, edición bloqueada.
        - **Exportar**: Excel con Leaderboard y Partidos (incluye canchas).
        - Próximo: formato Mexicano y modo espectador de solo lectura.
        """
    )
