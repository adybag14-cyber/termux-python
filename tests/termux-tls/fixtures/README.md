These public test certificates come from Cloudflare workerd's
`src/rust/cxx/kj-hyper/tls-test.rs` at tag `v1.20261104.1` (Apache-2.0).
They contain no private keys. `host.pem` names `example.com` and chains to
`ca.pem`; `other-ca.pem` is an unrelated test authority. The verification time
is fixed within the certificates' validity interval, with separate rejection
checks before and after that interval.
