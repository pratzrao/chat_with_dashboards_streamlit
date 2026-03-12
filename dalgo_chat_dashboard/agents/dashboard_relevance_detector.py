import logging
import re
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass
from openai import OpenAI
from config import config

logger = logging.getLogger(__name__)

@dataclass
class DashboardRelevanceResult:
    """Result of dashboard relevance analysis"""
    is_relevant_to_current: bool
    confidence: float  # 0.0 to 1.0
    relevant_dashboards: List[str]  # Dashboard IDs that might be relevant
    extracted_keywords: List[str]
    failure_reason: str  # Why no results were found
    suggested_action: str  # What user should do

class DashboardRelevanceDetector:
    """
    Detects whether a query is relevant to the current dashboard or other dashboards.
    Provides intelligent error messages when no results are found.
    """
    
    def __init__(self):
        self.openai_client = OpenAI(api_key=config.openai_api_key)
        
        # Dashboard knowledge base - will be updated dynamically
        self.dashboard_metadata: Dict[str, Dict] = {}
        self.program_keywords: Dict[str, Set[str]] = {}
        
    def update_dashboard_context(self, dashboard_graph: Dict):
        """Update the detector with dashboard metadata"""
        self.dashboard_metadata = {}
        self.program_keywords = {}
        
        dashboards = dashboard_graph.get('dashboards', {})
        
        for dashboard_id, dashboard_data in dashboards.items():
            dashboard = dashboard_data.get('dashboard')
            charts = dashboard_data.get('charts', [])
            
            if not dashboard:
                continue
                
            # Extract dashboard metadata
            title = getattr(dashboard, 'title', dashboard_id)
            description = getattr(dashboard, 'description', '')
            
            self.dashboard_metadata[dashboard_id] = {
                'title': title,
                'description': description,
                'charts': charts,
                'chart_count': len(charts)
            }
            
            # Extract keywords for this dashboard
            keywords = set()
            
            # Keywords from title and description
            title_words = self._extract_keywords(title.lower())
            desc_words = self._extract_keywords(description.lower())
            keywords.update(title_words)
            keywords.update(desc_words)
            
            # Keywords from chart titles and data sources
            for chart in charts:
                if hasattr(chart, 'title'):
                    chart_words = self._extract_keywords(chart.title.lower())
                    keywords.update(chart_words)
                
                if hasattr(chart, 'data_source'):
                    # Extract table/schema names as keywords
                    data_source = chart.data_source.lower()
                    if '.' in data_source:
                        schema, table = data_source.split('.', 1)
                        keywords.add(table)
                        keywords.add(schema)
                    else:
                        keywords.add(data_source)
            
            self.program_keywords[dashboard_id] = keywords
            
        logger.info(f"Updated dashboard context: {len(self.dashboard_metadata)} dashboards")
    
    def analyze_query_relevance(self, 
                              query: str, 
                              current_dashboard_id: Optional[str],
                              no_results_context: Dict) -> DashboardRelevanceResult:
        """
        Analyze why a query returned no results and provide contextual guidance.
        
        Args:
            query: The user's query
            current_dashboard_id: Currently selected dashboard
            no_results_context: Context about what failed (tables_found, vector_results, etc.)
        """
        
        # Extract keywords from query
        query_keywords = self._extract_keywords(query.lower())
        
        # Check relevance to current dashboard
        current_relevance = 0.0
        if current_dashboard_id and current_dashboard_id in self.program_keywords:
            current_keywords = self.program_keywords[current_dashboard_id]
            current_relevance = self._calculate_keyword_overlap(query_keywords, current_keywords)
        
        # Check relevance to other dashboards
        other_dashboard_scores = {}
        for dashboard_id, keywords in self.program_keywords.items():
            if dashboard_id != current_dashboard_id:
                score = self._calculate_keyword_overlap(query_keywords, keywords)
                if score > 0.2:  # Threshold for relevance
                    other_dashboard_scores[dashboard_id] = score
        
        # Sort other dashboards by relevance
        relevant_dashboards = sorted(other_dashboard_scores.items(), 
                                   key=lambda x: x[1], 
                                   reverse=True)[:3]  # Top 3
        
        # Determine failure reason and suggested action
        failure_reason, suggested_action = self._determine_failure_reason(
            query, current_relevance, relevant_dashboards, 
            current_dashboard_id, no_results_context
        )
        
        return DashboardRelevanceResult(
            is_relevant_to_current=current_relevance > 0.3,
            confidence=max(current_relevance, max([score for _, score in relevant_dashboards], default=0)),
            relevant_dashboards=[dash_id for dash_id, _ in relevant_dashboards],
            extracted_keywords=query_keywords,
            failure_reason=failure_reason,
            suggested_action=suggested_action
        )
    
    def _extract_keywords(self, text: str) -> Set[str]:
        """Extract meaningful keywords from text"""
        # Remove common stop words
        stop_words = {
            'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from',
            'has', 'he', 'in', 'is', 'it', 'its', 'of', 'on', 'that', 'the',
            'to', 'was', 'will', 'with', 'show', 'me', 'get', 'find', 'what',
            'how', 'many', 'much', 'count', 'total', 'data', 'information'
        }
        
        # Extract alphanumeric words
        words = re.findall(r'[a-zA-Z0-9_]+', text.lower())
        keywords = {word for word in words if len(word) > 2 and word not in stop_words}
        
        # Add compound keywords for common program terms
        text_lower = text.lower()
        compound_keywords = [
            'eco champions', 'ecochamps', 'eco_champs',
            'fellowship program', 'fellowship',
            'student assessment', 'student_assessment',
            'baseline assessment', 'midline assessment', 'endline assessment',
            'reading comprehension', 'math assessment',
            'school performance', 'teacher training'
        ]
        
        for compound in compound_keywords:
            if compound.replace('_', ' ').replace('_', '') in text_lower:
                # Add both compound and individual words
                keywords.add(compound.replace(' ', '_'))
                keywords.update(compound.replace('_', ' ').split())
        
        return keywords
    
    def _calculate_keyword_overlap(self, query_keywords: Set[str], dashboard_keywords: Set[str]) -> float:
        """Calculate keyword overlap between query and dashboard"""
        if not query_keywords or not dashboard_keywords:
            return 0.0
        
        # Direct overlap
        direct_overlap = len(query_keywords.intersection(dashboard_keywords))
        
        # Fuzzy matching for similar terms
        fuzzy_matches = 0
        for q_word in query_keywords:
            for d_word in dashboard_keywords:
                if len(q_word) > 3 and len(d_word) > 3:
                    # Check if one contains the other or they share significant prefix/suffix
                    if (q_word in d_word or d_word in q_word or 
                        q_word[:4] == d_word[:4] or q_word[-4:] == d_word[-4:]):
                        fuzzy_matches += 0.5
                        break
        
        total_matches = direct_overlap + fuzzy_matches
        return total_matches / len(query_keywords)
    
    def _determine_failure_reason(self, 
                                query: str,
                                current_relevance: float, 
                                relevant_dashboards: List[Tuple[str, float]],
                                current_dashboard_id: Optional[str],
                                no_results_context: Dict) -> Tuple[str, str]:
        """Determine the most likely reason for failure and suggest action"""
        
        # Check if query seems program-related at all
        program_indicators = {
            'student', 'school', 'teacher', 'assessment', 'score', 'grade',
            'fellowship', 'fellow', 'eco', 'champion', 'program', 'session',
            'baseline', 'midline', 'endline', 'reading', 'math', 'comprehension'
        }
        
        query_lower = query.lower()
        has_program_keywords = any(indicator in query_lower for indicator in program_indicators)
        
        # Scenario 1: Cross-dashboard question (high relevance to other dashboard, low to current)
        if relevant_dashboards and relevant_dashboards[0][1] > 0.4 and current_relevance < 0.2:
            top_dashboard_id = relevant_dashboards[0][0]
            top_dashboard_title = self.dashboard_metadata.get(top_dashboard_id, {}).get('title', top_dashboard_id)
            
            if current_dashboard_id:
                current_title = self.dashboard_metadata.get(current_dashboard_id, {}).get('title', current_dashboard_id)
                reason = f"cross_dashboard_question"
                action = f"This question appears to be about '{top_dashboard_title}' data, but you're currently viewing the '{current_title}' dashboard. Please switch to the '{top_dashboard_title}' dashboard to access that data."
            else:
                reason = "no_dashboard_selected" 
                action = f"This question appears to be about '{top_dashboard_title}' data. Please select the '{top_dashboard_title}' dashboard from the sidebar to access that data."
            
            return reason, action
        
        # Scenario 2: Relevant to current dashboard but no data found
        elif current_relevance > 0.3:
            # Check what specifically failed
            tables_found = no_results_context.get('tables_found', 0)
            vector_results = no_results_context.get('vector_results', 0)
            
            if tables_found == 0:
                reason = "no_relevant_tables"
                action = "I understand your question is about this dashboard's data, but couldn't find relevant tables. Try rephrasing your question or check if the data you're looking for exists in this dashboard."
            else:
                reason = "no_matching_data"
                action = "I found the relevant tables for this dashboard but no data matching your specific criteria. Try broadening your search terms, adjusting date ranges, or checking if that specific data is available."
            
            return reason, action
        
        # Scenario 3: Not program-related at all
        elif not has_program_keywords:
            reason = "irrelevant_question"
            action = "I can only help with questions about your organization's program data and metrics. Please ask about students, assessments, programs, or dashboard data."
            return reason, action
        
        # Scenario 4: Vague program question with no clear dashboard match
        else:
            reason = "vague_program_question"
            if current_dashboard_id:
                current_title = self.dashboard_metadata.get(current_dashboard_id, {}).get('title', current_dashboard_id)
                action = f"Your question seems program-related but I couldn't find matching data in the current '{current_title}' dashboard. Try being more specific about what data you want to see, or check if you need a different dashboard."
            else:
                available_dashboards = [self.dashboard_metadata.get(dash_id, {}).get('title', dash_id) 
                                      for dash_id in self.dashboard_metadata.keys()]
                action = f"Your question seems program-related but no dashboard is selected. Please choose a dashboard from: {', '.join(available_dashboards[:3])}."
            
            return reason, action
    
    def get_dashboard_suggestions(self, query: str) -> List[Dict[str, str]]:
        """Get dashboard suggestions based on query keywords"""
        query_keywords = self._extract_keywords(query.lower())
        suggestions = []
        
        for dashboard_id, keywords in self.program_keywords.items():
            score = self._calculate_keyword_overlap(query_keywords, keywords)
            if score > 0.1:  # Low threshold for suggestions
                dashboard_info = self.dashboard_metadata.get(dashboard_id, {})
                suggestions.append({
                    'dashboard_id': dashboard_id,
                    'title': dashboard_info.get('title', dashboard_id),
                    'description': dashboard_info.get('description', ''),
                    'relevance_score': score,
                    'chart_count': dashboard_info.get('chart_count', 0)
                })
        
        # Sort by relevance score
        suggestions.sort(key=lambda x: x['relevance_score'], reverse=True)
        return suggestions[:3]  # Return top 3