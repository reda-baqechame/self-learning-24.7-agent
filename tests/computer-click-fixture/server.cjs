const http = require('http');
const html = `<!doctype html><title>Bounded click fixture</title>
<style>a{display:block;position:absolute;left:40px;top:40px;width:180px;height:40px}</style>
<a href="/invoice/INV-0" data-invoice="INV-0">Download INV-0</a>
<script>window.activations=0;window.trustedActivations=0;document.addEventListener('click',e=>{
if(e.target.closest('a')){e.preventDefault();window.activations++;if(e.isTrusted)window.trustedActivations++;}});</script>`;
http.createServer((req,res)=>{res.setHeader('Content-Type','text/html');res.end(html);}).listen(8765,'127.0.0.1');
