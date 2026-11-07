#![allow(dead_code)]
include!("../../patches/workerd-termux-tls.rs");

#[cfg(test)]
mod tests {
    use super::*;
    use rustls::client::danger::ServerCertVerifier;
    use rustls::pki_types::pem::PemObject;
    use rustls::pki_types::{CertificateDer, ServerName, UnixTime};
    use std::path::PathBuf;
    use std::sync::Arc;

    fn bundle(name: &str) -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("fixtures")
            .join(name)
    }

    fn verifier(
        name: &str,
        extra: &[CertificateDer<'static>],
    ) -> Arc<rustls::client::WebPkiServerVerifier> {
        termux_root_verifier(
            &bundle(name),
            extra,
            Arc::new(rustls::crypto::ring::default_provider()),
        )
        .unwrap()
    }

    fn verify(verifier: &dyn ServerCertVerifier, name: &str, seconds: u64) -> bool {
        let cert = CertificateDer::from_pem_slice(include_bytes!("fixtures/host.pem")).unwrap();
        verifier
            .verify_server_cert(
                &cert,
                &[],
                &ServerName::try_from(name).unwrap(),
                &[],
                UnixTime::since_unix_epoch(std::time::Duration::from_secs(seconds)),
            )
            .is_ok()
    }

    #[test]
    fn accepts_a_valid_chain_from_the_termux_bundle() {
        assert!(verify(
            verifier("ca.pem", &[]).as_ref(),
            "example.com",
            1794000000
        ));
    }

    #[test]
    fn rejects_wrong_hostname() {
        assert!(!verify(
            verifier("ca.pem", &[]).as_ref(),
            "wrong.example.com",
            1794000000
        ));
    }

    #[test]
    fn rejects_invalid_certificate_time() {
        assert!(!verify(verifier("ca.pem", &[]).as_ref(), "example.com", 0));
        assert!(!verify(
            verifier("ca.pem", &[]).as_ref(),
            "example.com",
            8000000000
        ));
    }

    #[test]
    fn rejects_an_unknown_issuer() {
        assert!(!verify(
            verifier("other-ca.pem", &[]).as_ref(),
            "example.com",
            1794000000
        ));
    }

    #[test]
    fn retains_explicit_extra_roots() {
        let extra = CertificateDer::from_pem_slice(include_bytes!("fixtures/ca.pem")).unwrap();
        assert!(verify(
            verifier("other-ca.pem", &[extra]).as_ref(),
            "example.com",
            1794000000
        ));
    }

    #[test]
    fn refuses_missing_empty_and_malformed_bundles() {
        for name in ["missing.pem", "empty.pem", "malformed.pem"] {
            assert!(termux_root_verifier(
                &bundle(name),
                &[],
                Arc::new(rustls::crypto::ring::default_provider())
            )
            .is_err());
        }
    }
}
