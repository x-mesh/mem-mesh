/**
 * API 테스트 스크립트
 * 브라우저 콘솔에서 실행하여 API 상태를 확인
 */

// 전역 테스트 함수들
window.testAPI = {
  // 기본 API 테스트
  async testBasicAPI() {
    console.log('=== Basic API Test ===');
    
    try {
      // Health check
      const healthResponse = await fetch('/api/health');
      const health = await healthResponse.json();
      console.log('✅ Health check:', health);
      
      // Stats API
      const statsResponse = await fetch('/api/memories/stats');
      const stats = await statsResponse.json();
      console.log('✅ Stats API:', stats);
      
      // Search API (empty query)
      const searchResponse = await fetch('/api/memories/search?query= &limit=5');
      const searchResult = await searchResponse.json();
      console.log('✅ Search API (empty):', searchResult);
      
      // Search API (with query)
      const searchResponse2 = await fetch('/api/memories/search?query=test&limit=5');
      const searchResult2 = await searchResponse2.json();
      console.log('✅ Search API (with query):', searchResult2);
      
      return { success: true, message: 'All API tests passed' };
      
    } catch (error) {
      console.error('❌ API test failed:', error);
      return { success: false, error: error.message };
    }
  },
  
  // API Client 테스트
  async testAPIClient() {
    console.log('=== API Client Test ===');
    
    try {
      // API Client 로드
      const { APIClient } = await import('./js/services/api-client.js');
      const apiClient = new APIClient();
      
      console.log('✅ API Client created');
      
      // Stats 테스트
      const stats = await apiClient.getStats();
      console.log('✅ API Client stats:', stats);
      
      // Search 테스트
      const searchResult = await apiClient.searchMemories('', { limit: 5 });
      console.log('✅ API Client search:', searchResult);
      
      return { success: true, message: 'API Client tests passed' };
      
    } catch (error) {
      console.error('❌ API Client test failed:', error);
      return { success: false, error: error.message };
    }
  },
  
  // Search 페이지 컴포넌트 테스트
  async testSearchPage() {
    console.log('=== Search Page Test ===');
    
    try {
      // Search 페이지 로드
      const { SearchPage } = await import('./js/pages/search.js');
      
      console.log('✅ Search page component loaded');
      
      // 가짜 앱 객체 생성
      if (!window.app) {
        const { APIClient } = await import('./js/services/api-client.js');
        window.app = {
          apiClient: new APIClient()
        };
        console.log('✅ Mock app created');
      }
      
      // Search 페이지 인스턴스 생성
      const searchPage = new SearchPage();
      searchPage.searchQuery = '';
      searchPage.selectedCategory = '';
      searchPage.selectedProject = '';
      searchPage.pageSize = 5;
      
      console.log('✅ Search page instance created');
      
      // Direct search 테스트
      await searchPage.performDirectSearch();
      console.log('✅ Direct search completed, results:', searchPage.searchResults.length);
      
      // Regular search 테스트 (앱이 있는 경우)
      if (window.app && window.app.apiClient) {
        await searchPage.performSearch();
        console.log('✅ Regular search completed, results:', searchPage.searchResults.length);
      }
      
      return { success: true, message: 'Search page tests passed', results: searchPage.searchResults.length };
      
    } catch (error) {
      console.error('❌ Search page test failed:', error);
      return { success: false, error: error.message };
    }
  },
  
  // 전체 테스트 실행
  async runAllTests() {
    console.log('🚀 Running all API tests...');
    
    const results = {
      basicAPI: await this.testBasicAPI(),
      apiClient: await this.testAPIClient(),
      searchPage: await this.testSearchPage()
    };
    
    console.log('📊 Test Results Summary:');
    console.table(results);
    
    const allPassed = Object.values(results).every(r => r.success);
    console.log(allPassed ? '🎉 All tests passed!' : '⚠️ Some tests failed');
    
    return results;
  }
};

console.log('🔧 API Test utilities loaded. Run window.testAPI.runAllTests() to test everything.');