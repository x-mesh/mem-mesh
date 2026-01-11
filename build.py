#!/usr/bin/env python3
"""
mem-mesh Web UI Build Script
Optimizes and prepares the web UI for production deployment
"""

import os
import json
import shutil
import gzip
import hashlib
from pathlib import Path
from datetime import datetime

class WebUIBuilder:
    def __init__(self, source_dir="static", build_dir="dist"):
        self.source_dir = Path(source_dir)
        self.build_dir = Path(build_dir)
        self.manifest = {}
        
    def build(self):
        """Run the complete build process"""
        print("🏗️  Starting mem-mesh Web UI build...")
        
        # Clean build directory
        self.clean_build_dir()
        
        # Copy and process files
        self.copy_html_files()
        self.process_css_files()
        self.process_js_files()
        self.copy_assets()
        
        # Generate manifest
        self.generate_manifest()
        
        # Create compressed versions
        self.create_compressed_files()
        
        # Generate build info
        self.generate_build_info()
        
        print("✅ Build completed successfully!")
        print(f"📦 Output directory: {self.build_dir}")
        
    def clean_build_dir(self):
        """Clean the build directory"""
        if self.build_dir.exists():
            shutil.rmtree(self.build_dir)
        self.build_dir.mkdir(parents=True, exist_ok=True)
        print(f"🧹 Cleaned build directory: {self.build_dir}")
        
    def copy_html_files(self):
        """Copy and process HTML files"""
        html_files = list(self.source_dir.glob("*.html"))
        
        for html_file in html_files:
            dest_file = self.build_dir / html_file.name
            
            # Read and process HTML
            content = html_file.read_text(encoding='utf-8')
            
            # Add cache busting and optimization meta tags
            content = self.add_optimization_meta(content)
            
            # Write processed HTML
            dest_file.write_text(content, encoding='utf-8')
            print(f"📄 Processed HTML: {html_file.name}")
            
    def add_optimization_meta(self, html_content):
        """Add optimization meta tags to HTML"""
        meta_tags = '''
    <!-- Performance and SEO optimizations -->
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="theme-color" content="#3b82f6">
    <meta name="description" content="mem-mesh Web UI - Memory management and search interface">
    
    <!-- Preload critical resources -->
    <link rel="preload" href="css/main.css" as="style">
    <link rel="preload" href="js/main.js" as="script">
    
    <!-- DNS prefetch for external resources -->
    <link rel="dns-prefetch" href="//d3js.org">
    
    <!-- Service Worker registration -->
    <script>
        if ('serviceWorker' in navigator) {
            window.addEventListener('load', () => {
                navigator.serviceWorker.register('/sw.js')
                    .then(registration => console.log('SW registered'))
                    .catch(error => console.log('SW registration failed'));
            });
        }
    </script>'''
        
        # Insert meta tags after <head>
        if '<head>' in html_content:
            html_content = html_content.replace('<head>', f'<head>{meta_tags}')
            
        return html_content
        
    def process_css_files(self):
        """Process and optimize CSS files"""
        css_dir = self.source_dir / "css"
        if not css_dir.exists():
            return
            
        build_css_dir = self.build_dir / "css"
        build_css_dir.mkdir(exist_ok=True)
        
        for css_file in css_dir.glob("*.css"):
            content = css_file.read_text(encoding='utf-8')
            
            # Basic CSS minification
            content = self.minify_css(content)
            
            # Generate hash for cache busting
            file_hash = self.generate_hash(content)
            filename = f"{css_file.stem}.{file_hash[:8]}.css"
            
            dest_file = build_css_dir / filename
            dest_file.write_text(content, encoding='utf-8')
            
            self.manifest[f"css/{css_file.name}"] = f"css/{filename}"
            print(f"🎨 Processed CSS: {css_file.name} -> {filename}")
            
    def process_js_files(self):
        """Process and optimize JavaScript files"""
        js_dir = self.source_dir / "js"
        if not js_dir.exists():
            return
            
        build_js_dir = self.build_dir / "js"
        build_js_dir.mkdir(exist_ok=True)
        
        # Process JS files recursively
        for js_file in js_dir.rglob("*.js"):
            relative_path = js_file.relative_to(js_dir)
            dest_dir = build_js_dir / relative_path.parent
            dest_dir.mkdir(parents=True, exist_ok=True)
            
            content = js_file.read_text(encoding='utf-8')
            
            # Basic JS minification (remove comments and extra whitespace)
            content = self.minify_js(content)
            
            # Generate hash for cache busting (only for main files)
            if relative_path.parent == Path('.'):
                file_hash = self.generate_hash(content)
                filename = f"{js_file.stem}.{file_hash[:8]}.js"
                self.manifest[f"js/{js_file.name}"] = f"js/{filename}"
            else:
                filename = js_file.name
                
            dest_file = dest_dir / filename
            dest_file.write_text(content, encoding='utf-8')
            
            print(f"📜 Processed JS: {relative_path} -> {dest_dir.name}/{filename}")
            
    def copy_assets(self):
        """Copy static assets"""
        assets_dirs = ["images", "fonts", "icons"]
        
        for assets_dir in assets_dirs:
            source_assets = self.source_dir / assets_dir
            if source_assets.exists():
                dest_assets = self.build_dir / assets_dir
                shutil.copytree(source_assets, dest_assets)
                print(f"📁 Copied assets: {assets_dir}")
                
    def minify_css(self, css_content):
        """Basic CSS minification"""
        import re
        
        # Remove comments
        css_content = re.sub(r'/\*.*?\*/', '', css_content, flags=re.DOTALL)
        
        # Remove extra whitespace
        css_content = re.sub(r'\s+', ' ', css_content)
        css_content = re.sub(r';\s*}', '}', css_content)
        css_content = re.sub(r'{\s*', '{', css_content)
        css_content = re.sub(r'}\s*', '}', css_content)
        css_content = re.sub(r':\s*', ':', css_content)
        css_content = re.sub(r';\s*', ';', css_content)
        
        return css_content.strip()
        
    def minify_js(self, js_content):
        """Basic JavaScript minification"""
        import re
        
        # Remove single-line comments (but preserve URLs)
        js_content = re.sub(r'(?<!:)//.*$', '', js_content, flags=re.MULTILINE)
        
        # Remove multi-line comments
        js_content = re.sub(r'/\*.*?\*/', '', js_content, flags=re.DOTALL)
        
        # Remove extra whitespace (but preserve string literals)
        lines = js_content.split('\n')
        minified_lines = []
        
        for line in lines:
            line = line.strip()
            if line:
                minified_lines.append(line)
                
        return '\n'.join(minified_lines)
        
    def generate_hash(self, content):
        """Generate hash for cache busting"""
        return hashlib.md5(content.encode('utf-8')).hexdigest()
        
    def generate_manifest(self):
        """Generate asset manifest for cache busting"""
        manifest_file = self.build_dir / "manifest.json"
        manifest_file.write_text(json.dumps(self.manifest, indent=2))
        print(f"📋 Generated manifest: {len(self.manifest)} entries")
        
    def create_compressed_files(self):
        """Create gzipped versions of text files"""
        text_extensions = ['.html', '.css', '.js', '.json', '.svg']
        
        for file_path in self.build_dir.rglob("*"):
            if file_path.is_file() and file_path.suffix in text_extensions:
                # Create gzipped version
                gz_path = file_path.with_suffix(file_path.suffix + '.gz')
                
                with open(file_path, 'rb') as f_in:
                    with gzip.open(gz_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                        
                # Check compression ratio
                original_size = file_path.stat().st_size
                compressed_size = gz_path.stat().st_size
                ratio = (1 - compressed_size / original_size) * 100
                
                print(f"🗜️  Compressed {file_path.name}: {ratio:.1f}% reduction")
                
    def generate_build_info(self):
        """Generate build information"""
        build_info = {
            "build_time": datetime.now().isoformat(),
            "version": "1.0.0",
            "environment": "production",
            "features": [
                "Web Components",
                "Virtual Scrolling",
                "Keyboard Shortcuts",
                "Toast Notifications",
                "Dark/Light Theme",
                "Responsive Design",
                "PWA Ready"
            ],
            "browser_support": {
                "chrome": ">=88",
                "firefox": ">=85",
                "safari": ">=14",
                "edge": ">=88"
            },
            "performance": {
                "lighthouse_target": {
                    "performance": ">= 90",
                    "accessibility": ">= 95",
                    "best_practices": ">= 90",
                    "seo": ">= 90"
                }
            }
        }
        
        build_info_file = self.build_dir / "build-info.json"
        build_info_file.write_text(json.dumps(build_info, indent=2))
        print("📊 Generated build info")
        
    def create_service_worker(self):
        """Create service worker for offline support"""
        sw_content = '''
// mem-mesh Web UI Service Worker
const CACHE_NAME = 'mem-mesh-v1';
const STATIC_ASSETS = [
    '/',
    '/css/main.css',
    '/js/main.js',
    '/manifest.json'
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => cache.addAll(STATIC_ASSETS))
    );
});

self.addEventListener('fetch', (event) => {
    event.respondWith(
        caches.match(event.request)
            .then(response => {
                if (response) {
                    return response;
                }
                return fetch(event.request);
            })
    );
});
'''
        
        sw_file = self.build_dir / "sw.js"
        sw_file.write_text(sw_content)
        print("⚙️  Created service worker")

def main():
    """Main build function"""
    builder = WebUIBuilder()
    builder.build()
    builder.create_service_worker()
    
    print("\n🎉 Build Summary:")
    print("- Optimized CSS and JavaScript files")
    print("- Generated cache-busting hashes")
    print("- Created compressed (gzip) versions")
    print("- Added performance optimizations")
    print("- Generated service worker for offline support")
    print("- Ready for production deployment!")

if __name__ == "__main__":
    main()