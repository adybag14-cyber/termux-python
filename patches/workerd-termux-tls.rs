// Termux is a native CLI process without Android's Java TrustManager. Use the
// installed CA bundle and rustls' normal chain, time, and hostname verification.
fn termux_root_verifier(
    bundle: &std::path::Path,
    extra: &[rustls::pki_types::CertificateDer<'static>],
    provider: std::sync::Arc<rustls::crypto::CryptoProvider>,
) -> std::result::Result<
    std::sync::Arc<rustls::client::WebPkiServerVerifier>,
    Box<dyn std::error::Error + Send + Sync>,
> {
    use rustls::pki_types::pem::PemObject as _;
    let pem = std::fs::read(bundle)?;
    let certs = rustls::pki_types::CertificateDer::pem_slice_iter(&pem)
        .collect::<std::result::Result<Vec<_>, _>>()?;
    let mut roots = rustls::RootCertStore::empty();
    let (added, _) = roots.add_parsable_certificates(certs);
    if added == 0 {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            "Termux CA bundle contains no usable certificates",
        )
        .into());
    }
    for cert in extra {
        // Preserve workerd's separate direct-trust handling of certificates
        // that cannot also serve as webpki trust anchors.
        let _ = roots.add(cert.clone());
    }
    Ok(rustls::client::WebPkiServerVerifier::builder_with_provider(
        std::sync::Arc::new(roots),
        provider,
    )
    .build()?)
}
