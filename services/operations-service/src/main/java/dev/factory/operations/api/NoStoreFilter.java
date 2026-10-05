package dev.factory.operations.api;

import java.io.IOException;
import jakarta.servlet.*;
import jakarta.servlet.http.*;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
@Profile("!bootstrap")
public class NoStoreFilter extends OncePerRequestFilter {
    @Override protected void doFilterInternal(HttpServletRequest request,HttpServletResponse response,FilterChain chain) throws ServletException,IOException {
        if(request.getRequestURI().startsWith("/api/v1/") || request.getRequestURI().startsWith("/internal/v1/")) response.setHeader("Cache-Control","no-store");
        chain.doFilter(request,response);
    }
}
