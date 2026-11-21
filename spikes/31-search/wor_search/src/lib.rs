//! The only search functions Wisdom of Reddit needs, over Jammi's Rust API.
//! Python keeps the web app and sqlite; this crate keeps BM25 and RRF.
use jammi_ai::index::LexicalIndex;
use jammi_ai::query::{rrf_fuse, DEFAULT_K_RRF};
use jammi_db::index::{Admission, LexicalAnalyzer};
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;

fn err(e: impl std::fmt::Display) -> PyErr {
    PyRuntimeError::new_err(e.to_string())
}

/// A BM25 index over (comment_id, body) rows. In memory: Jammi 0.54 never
/// persists a LexicalIndex, so the app builds it at startup.
#[pyclass]
struct Bm25 {
    rows: Vec<(String, String)>,
    index: LexicalIndex,
}

#[pymethods]
impl Bm25 {
    #[new]
    fn new(py: Python<'_>, rows: Vec<(String, String)>) -> PyResult<Self> {
        let index = py
            .detach(|| LexicalIndex::build(rows.iter().map(|(i, b)| (i, b)), LexicalAnalyzer::English))
            .map_err(err)?;
        Ok(Self { rows, index })
    }

    /// Top `k` comment ids with BM25 scores.
    fn search(&self, py: Python<'_>, query: &str, k: usize) -> PyResult<Vec<(String, f32)>> {
        let hits = py.detach(|| self.index.search(query, k, &Admission::Every)).map_err(err)?;
        Ok(hits.into_iter().map(|h| (h.row_id, h.bm25_score)).collect())
    }

    /// Add a month. LexicalIndex has no insert, so this rebuilds over all rows.
    fn add_month(&mut self, py: Python<'_>, rows: Vec<(String, String)>) -> PyResult<()> {
        self.rows.extend(rows);
        let all = &self.rows;
        self.index = py
            .detach(|| LexicalIndex::build(all.iter().map(|(i, b)| (i, b)), LexicalAnalyzer::English))
            .map_err(err)?;
        Ok(())
    }

    fn __len__(&self) -> usize {
        self.index.len() as usize
    }
}

/// Reciprocal-rank fusion of ranked id lists (e.g. BM25 + vector).
#[pyfunction]
#[pyo3(signature = (ranked_lists, k_rrf=None))]
fn rrf(ranked_lists: Vec<Vec<String>>, k_rrf: Option<u32>) -> Vec<(String, f64)> {
    rrf_fuse(&ranked_lists, k_rrf.unwrap_or(DEFAULT_K_RRF))
        .into_iter()
        .map(|h| (h.row_id, h.rrf_score))
        .collect()
}

#[pymodule]
fn wor_search(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Bm25>()?;
    m.add_function(wrap_pyfunction!(rrf, m)?)?;
    Ok(())
}
